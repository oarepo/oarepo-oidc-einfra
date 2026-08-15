# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Entitlements parsed from URN8141 and applied to users."""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, override

from flask import current_app
from invenio_accounts.proxies import current_datastore
from invenio_audit_logs.services import AuditLogOp
from invenio_communities.members.records.api import Member
from invenio_communities.members.records.models import CommunityMetadata, MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from invenio_db.uow import ModelCommitOp, ModelDeleteOp, UnitOfWork
from invenio_records_resources.services.uow import RecordIndexDeleteOp, RecordIndexOp, TaskOp
from invenio_users_resources.services.users.tasks import reindex_users
from urnparse import URN8141

from oarepo_oidc_einfra.audit_log import (
    CommunityMemberAddedAuditLog,
    CommunityMemberRemovedAuditLog,
    RoleMemberAddedAuditLog,
    RoleMemberRemovedAuditLog,
    audit_log,
)
from oarepo_oidc_einfra.models import EInfraUserEntitlements

if TYPE_CHECKING:
    from invenio_accounts.models import Role, User

log = logging.getLogger("perun.entitlements")


class EntitlementError(ValueError):
    """Raised when an entitlement string can not be parsed or resolved.

    This is the only exception type raised from entitlement parsing (:py:meth:`Entitlement.from_string`
    and the ``from_slug``/``from_role_name`` constructors), regardless of the underlying cause
    (malformed URN, unknown namespace/prefix/type, or an unknown/deleted community or role).
    """


class BadEntitlementTypeError(EntitlementError):
    """Raised when the type in an entitlement string can not be resolved."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entitlement:
    """Represents an entitlement parsed from a URN8141.

    A Perun entitlement looks like: urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz
    """

    entitlement: str

    @classmethod
    def from_string(cls, entitlement: str) -> Entitlement:
        """Parse an entitlement from a URN8141."""
        try:
            urn = URN8141.from_string(entitlement)
        except Exception as e:
            raise EntitlementError(f"Malformed entitlement URN: {entitlement}") from e
        parts: list[str] = urn.specific_string.parts

        if urn.namespace_id.value not in current_app.config["EINFRA_ENTITLEMENT_NAMESPACES"]:
            raise EntitlementError(f"Unknown entitlement namespace: {urn.namespace_id.value}")

        if not parts or parts[0] != current_app.config["EINFRA_ENTITLEMENT_PREFIX"]:
            raise EntitlementError(f"Unknown entitlement prefix: {parts[0]}")

        match parts[1:]:
            case "res", "communities", community_slug, "role", role:
                return CommunityEntitlement.from_slug(entitlement=entitlement, community_slug=community_slug, role=role)
            case "res", "roles", role:
                return GlobalRoleEntitlement.from_role_name(entitlement=entitlement, role=role)

        raise BadEntitlementTypeError(f"Unknown entitlement type: {parts}")

    @override
    def __str__(self) -> str:
        return self.entitlement

    @override
    def __repr__(self) -> str:
        return repr(self.entitlement)

    @property
    def sort_key(self) -> int:
        """Return a sort key for the entitlement."""
        return 0

    @property
    def core(self) -> tuple[str, ...]:
        """Return the "core" of the entitlement.

        Only one entitlement for a user can have the same core.
        """
        return ()

    def apply(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Apply the entitlement to the user."""

    def remove(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Remove the entitlement from the user."""

    @classmethod
    def deduplicate_by_core(cls, entitlements: list[Entitlement]) -> list[Entitlement]:
        """Filter the entitlements to remove duplicates based on core.

        For the duplicates, return the one with the highest sort key.
        """
        by_core = defaultdict(list)
        for ent in entitlements:
            by_core[ent.core].append(ent)

        return [max(vals, key=lambda e: e.sort_key) for vals in by_core.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CommunityEntitlement(Entitlement):
    """Represents a community entitlement parsed from a URN8141."""

    community: CommunityMetadata
    role: str

    @classmethod
    def from_slug(cls, *, entitlement: str, community_slug: str, role: str) -> CommunityEntitlement:
        """Create a community entitlement, looking up the community by its slug and validating the role."""
        roles = current_app.config["COMMUNITIES_ROLES"]
        if not any(r["name"] == role for r in roles):
            raise EntitlementError(f"Unknown community role: {role}")

        community = db.session.query(CommunityMetadata).filter_by(slug=community_slug).first()
        if community is None:
            raise EntitlementError(f"Unknown community: {community_slug}")
        return cls(entitlement=entitlement, community=community, role=role)

    @property
    def community_slug(self) -> str:
        """Return the slug of the community for this entitlement."""
        return self.community.slug

    @override
    @property
    def sort_key(self) -> int:
        for idx, r in enumerate(current_app.config["COMMUNITIES_ROLES"]):
            if r["name"] == self.role:
                return len(current_app.config["COMMUNITIES_ROLES"]) - idx
        return -1

    @override
    @property
    def core(self) -> tuple[str, ...]:
        """Return the "core" of the entitlement.

        Only one entitlement for a user can have the same core.
        """
        return "community", self.community_slug

    @override
    def apply(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Apply the entitlement to the user."""
        community = self.community
        db_member = db.session.query(MemberModel).filter_by(community_id=community.id, user_id=user.id).first()
        index_required = False
        if db_member is not None:
            if not db_member.active or db_member.role != self.role:
                db_member.active = True
                db_member.role = self.role
                uow.register(ModelCommitOp(db_member))
                index_required = True
                audit_data = CommunityMemberAddedAuditLog.build(user, community.slug, role=self.role, cause=cause)
                if audit_data is not None:
                    uow.register(AuditLogOp(audit_data))
        else:
            # create a new member
            db_member = MemberModel(
                community_id=community.id,
                role=self.role,
                visible=False,
                user_id=user.id,
                active=True,
            )
            uow.register(ModelCommitOp(db_member))
            index_required = True
            audit_data = CommunityMemberAddedAuditLog.build(user, community.slug, role=self.role, cause=cause)
            if audit_data is not None:
                uow.register(AuditLogOp(audit_data))

        if index_required:
            model = Member({}, model=db_member)  # ty: ignore[invalid-argument-type]
            uow.register(RecordIndexOp(model, indexer=current_communities.service.members.indexer))

    @override
    def remove(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Remove the entitlement from the user."""
        community = self.community
        db_member = (
            db.session.query(MemberModel)
            .filter_by(
                community_id=community.id,
                user_id=user.id,
            )
            .first()
        )
        if db_member is not None:
            model = Member({}, model=db_member)  # ty: ignore[invalid-argument-type]
            uow.register(ModelDeleteOp(db_member))
            uow.register(RecordIndexDeleteOp(model, indexer=current_communities.service.members.indexer))
            audit_data = CommunityMemberRemovedAuditLog.build(user, community.slug, cause=cause)
            if audit_data is not None:
                uow.register(AuditLogOp(audit_data))


@dataclasses.dataclass(frozen=True, kw_only=True)
class GlobalRoleEntitlement(Entitlement):
    """Represents a global role entitlement parsed from a URN8141."""

    role: Role

    @classmethod
    def from_role_name(cls, *, entitlement: str, role: str) -> GlobalRoleEntitlement:
        """Create a global role entitlement, looking up the role by its name."""
        role_obj = current_datastore.find_role(role)
        if role_obj is None:
            raise EntitlementError(f"Unknown role: {role}")
        return cls(entitlement=entitlement, role=role_obj)

    @property
    def role_name(self) -> str:
        """Return the name of the role for this entitlement."""
        return self.role.name

    @override
    @property
    def sort_key(self) -> int:
        return -1

    @override
    @property
    def core(self) -> tuple[str, ...]:
        """Return the "core" of the entitlement.

        Only one entitlement for a user can have the same core.
        """
        return "role", self.role_name

    @override
    def apply(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Apply the entitlement to the user."""
        if self.role not in user.roles:  # ty: ignore[unsupported-operator]
            user.roles.append(self.role)
            uow.register(ModelCommitOp(user))
            uow.register(TaskOp(reindex_users, [user.id]))
            audit_data = RoleMemberAddedAuditLog.build(user, self.role_name, cause=cause)
            if audit_data is not None:
                uow.register(AuditLogOp(audit_data))

    @override
    def remove(self, user: User, cause: str, uow: UnitOfWork) -> None:
        """Remove the entitlement from the user."""
        if self.role in user.roles:  # ty: ignore[unsupported-operator]
            user.roles.remove(self.role)
            uow.register(ModelCommitOp(user))
            uow.register(TaskOp(reindex_users, [user.id]))
            audit_data = RoleMemberRemovedAuditLog.build(user, self.role_name, cause=cause)
            if audit_data is not None:
                uow.register(AuditLogOp(audit_data))


def update_user_entitlements(user: User, new_entitlements: set[Entitlement], cause: str) -> None:
    """Update the user's entitlements based on the new set of entitlements."""
    new_entitlements = set(Entitlement.deduplicate_by_core(list(new_entitlements)))

    known_entitlements = _collect_known_entitlements(user)

    with UnitOfWork() as uow:
        for entitlement in known_entitlements - new_entitlements:
            try:
                entitlement.remove(user, cause, uow)
            except BadEntitlementTypeError as e:
                # expected for non-resource entitlement types - not an audit-worthy failure
                log.debug("Failed to remove entitlement %s: %s", entitlement, e)
            except Exception:  # noqa BLE001 log if the entitlement fails to be removed
                audit_log.exception("Failed to remove entitlement %s (cause: %s)", entitlement, cause)

        # process in ascending order of sort key - that way "owner" will get priority
        # even if the user is member as well
        for entitlement in sorted(new_entitlements, key=lambda e: e.sort_key):
            try:
                entitlement.apply(user, cause, uow)
            except BadEntitlementTypeError as e:
                # expected for non-resource entitlement types - not an audit-worthy failure
                log.debug("Failed to add entitlement %s: %s", entitlement, e)
            except Exception:  # noqa BLE001 log if the entitlement fails to apply
                audit_log.exception("Failed to add entitlement %s (cause: %s)", entitlement, cause)

        # upsert the EInfraUserEntitlements - if there are no new entitlements, leave any
        # previously stored ones untouched rather than overwriting them with an empty list,
        # unless the user actually had entitlements before, in which case the row is removed
        if new_entitlements:
            user_entitlements = EInfraUserEntitlements(user_id=user.id, entitlements=[str(e) for e in new_entitlements])
            db.session.merge(user_entitlements)
        elif known_entitlements:
            db.session.query(EInfraUserEntitlements).filter_by(user_id=user.id).delete()

        uow.commit()


def _collect_known_entitlements(user: User) -> set[Entitlement]:
    """Collect the known entitlements for the user from the database."""
    known_entitlements = set()
    for cap in db.session.query(EInfraUserEntitlements.entitlements).filter_by(user_id=user.id).scalar() or []:
        try:
            known_entitlements.add(Entitlement.from_string(cap))
        except BadEntitlementTypeError as e:
            log.debug("Ignoring stored entitlement %s: %s", cap, e)
        except EntitlementError as e:
            # the community/role referenced by this entitlement might have been
            # deleted since it was stored - ignore it rather than fail the whole update
            log.info("Ignoring stored entitlement %s: %s", cap, e)
    return known_entitlements
