#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Helper functions for working with communities."""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from collections.abc import Iterable
from functools import cached_property
from typing import TYPE_CHECKING
from uuid import UUID

from flask import current_app, flash
from invenio_access.permissions import system_identity
from invenio_communities.communities.records.api import Community
from invenio_communities.members.errors import AlreadyMemberError
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from invenio_i18n import gettext as _
from sqlalchemy import select

from oarepo_oidc_einfra.proxies import current_einfra_oidc

if TYPE_CHECKING:
    from uuid import UUID

    from invenio_accounts.models import User

log = logging.getLogger("perun.communities")


@dataclasses.dataclass(frozen=True)
class CommunityRole:
    """A class representing a community and a role."""

    community_id: UUID
    role: str


class CommunitySupport:
    """A support class for working with communities and their members."""

    @cached_property
    def slug_to_id(self) -> dict[str, UUID]:
        """Returns a mapping of community slugs to their ids."""
        return {
            row[1]: row[0]
            for row in db.session.execute(  # type: ignore
                select(Community.model_cls.id, Community.model_cls.slug)
            )
        }

    @cached_property
    def all_community_roles(self) -> set[CommunityRole]:
        """Return a set of all community roles (pair of community id, role name) known to the repository.

        :return:                    a set of all community roles known to the repository
        """
        repository_comunity_roles = set()
        community_roles = self.role_names

        for community in Community.model_cls.query.all():
            for role in community_roles:
                repository_comunity_roles.add(CommunityRole(community.id, role))
        return repository_comunity_roles

    @cached_property
    def role_names(self) -> set[str]:
        """Return a set of all known community role names, as configured inside the invenio.cfg.

        :return:                a set of all known community role names
        """
        return {role["name"] for role in current_app.config["COMMUNITIES_ROLES"]}

    def role_priority(self, role_name: str) -> int:
        """Return a priority of a given role name.

        :param role_name:       role name
        :return:                role priority (0 is lowest (member), higher number is higher priority (up to owner))
        """
        return self.role_priorities[role_name]

    @cached_property
    def role_priorities(self) -> dict[str, int]:
        """Returns a mapping of role names to their priorities.

        :return:                a mapping of role names to their priorities, 0 is lowest priority
        """
        return {
            role["name"]: len(current_app.config["COMMUNITIES_ROLES"]) - role_idx
            for role_idx, role in enumerate(current_app.config["COMMUNITIES_ROLES"])
        }

    @classmethod
    def set_user_community_membership(
        cls,
        user: User,
        new_community_roles: set[CommunityRole],
        current_community_roles: set[CommunityRole] | None = None,
    ) -> None:
        """Set user membership based on the new community roles.

        The previous community roles, not present in new_community_roles, are removed.

        :param user:                    User object for which communities will be set
        :param new_community_roles:     Set of new community roles
        :param current_community_roles: Set of current community roles. If not passed, it is fetched from the database.
        """
        if not current_community_roles:
            current_community_roles = cls.get_user_community_membership(user)

        for v in new_community_roles:
            assert isinstance(v, CommunityRole)

        # The role transformer is a function that can be used to transform the roles
        # before they are set for the user. It can be used to implement custom logic,
        # such as filtering out certain roles or changing the role names.
        #
        # Example: make everyone who logs in as a member of the generic community
        # This can not be implemented on the AAI side as "members" group in AAI
        # can not be assigned a resource with capabilities.
        if current_einfra_oidc.role_transformer:
            current_einfra_oidc.role_transformer(
                user, current_community_roles, new_community_roles
            )

        # find if any community memberships are duplicated and if so,
        # keep only the one with the highest priority
        cls._remove_duplicate_roles(new_community_roles, user)

        # provide breadcrumbs for glitchtip
        log.info(
            "Current community roles for user %s: %s", user.id, current_community_roles
        )
        log.info("New community roles for user %s: %s", user.id, new_community_roles)

        for community_role in current_community_roles - new_community_roles:
            try:
                cls._remove_user_community_membership(community_role.community_id, user)
            except Exception as e:
                # This is a case when the user is the last member of a community -
                # in this case he can not be removed. This should happen only
                # for community owners, as they are the last members of a community.
                # In this case we just log the error and continue.
                log.error(
                    "Failed to remove user %s from community %s: "
                    "current_community_roles=%s new_community_roles=%s: "
                    "Exception: %s",
                    user.id,
                    community_role,
                    current_community_roles,
                    new_community_roles,
                    e,
                )

        for community_role in new_community_roles - current_community_roles:
            try:
                # note: this takes care of the case when there is an existing
                # invitation request for the user in the community
                # and the user has already accepted it inside AAI
                cls._add_user_community_membership(community_role, user)
            except Exception as e:
                # If unexpected error occurs, rather than failing the whole login
                # process, we log the error and continue. User will not be added
                # to the community, but at least they can log in.
                # The error will be recorded to glitchtip and can be investigated later.
                log.error(
                    "Failed to add user %s to community %s with role %s: "
                    "current_community_roles=%s new_community_roles=%s: "
                    "Exception: %s",
                    user.id,
                    community_role.community_id,
                    community_role.role,
                    current_community_roles,
                    new_community_roles,
                    e,
                )

    @classmethod
    def _remove_duplicate_roles(
        cls, new_community_roles: set[CommunityRole], user: User
    ) -> None:
        roles_by_community_id = defaultdict[UUID, set[CommunityRole]](set)
        for community_role in new_community_roles:
            roles_by_community_id[community_role.community_id].add(community_role)

        for community_id, roles in roles_by_community_id.items():
            if len(roles) > 1:
                # get roles and their priorities, 0 is the highest priority
                community_roles_with_priorities = {
                    role["name"]: idx
                    for idx, role in enumerate(current_app.config["COMMUNITIES_ROLES"])
                }
                # sort roles by their priority, highest priority first
                sorted_roles: list[CommunityRole] = sorted(
                    roles,
                    key=lambda r: community_roles_with_priorities[r.role],
                )
                log.error(
                    "User %s has multiple roles in community %s: %s. Will keep only %s",
                    user.id,
                    community_id,
                    sorted_roles,
                    sorted_roles[0],
                )
                for role in sorted_roles[1:]:
                    # remove all but the highest priority role
                    new_community_roles.remove(role)

    @classmethod
    def get_user_community_membership(
        cls, user: User, active: bool = True
    ) -> set[CommunityRole]:
        """Get user's actual community roles.

        :param user: User object
        """
        ret = set()
        for row in db.session.execute(  # type: ignore
            select([MemberModel.community_id, MemberModel.role]).where(
                MemberModel.user_id == user.id, MemberModel.active == active
            )
        ):
            ret.add(CommunityRole(row.community_id, row.role))

        return ret

    @classmethod
    def get_user_list_community_membership(
        cls, user_ids: Iterable[int], active: bool = True
    ) -> dict[int, set[CommunityRole]]:
        """Get community roles of a list of users.

        :param user_ids: List of user ids
        """
        ret: dict[int, set[CommunityRole]] = {}
        for row in db.session.execute(  # type: ignore
            select(
                [MemberModel.community_id, MemberModel.user_id, MemberModel.role]
            ).where(
                MemberModel.user_id.in_(user_ids), MemberModel.active == active
            )  # type: ignore
        ):
            if row.user_id not in ret:
                ret[row.user_id] = set()
            ret[row.user_id].add(CommunityRole(row.community_id, row.role))

        return ret

    @classmethod
    def _add_user_community_membership(
        cls, community_role: CommunityRole, user: User
    ) -> None:
        """Add user to a community with a given role.

        :param community_role:          community role
        :param user:                    user object
        :return:                        A membership result item from service
        """
        data = {
            "role": community_role.role,
            "members": [{"type": "user", "id": str(user.id)}],
        }
        log.info(
            "Adding user %s to community %s with role %s",
            user.id,
            community_role.community_id,
            community_role.role,
        )
        try:
            ret = current_communities.service.members.add(
                system_identity, community_role.community_id, data
            )
            log.info(
                "User %s added to community %s with role %s",
                user.id,
                community_role.community_id,
                community_role.role,
            )
            return ret
        except AlreadyMemberError:
            # We are here because
            #
            # * active memberships have not returned this (community, role) for user
            # * but the new membership could not be created because there already is a one
            #
            # This means that there is an invitation request for this user in repository
            # and the user has already accepted it inside AAI (as the community/role pair arrived from AAI).
            #
            # We need to get the associated invitation request and accept it here,
            # thus the membership will become active.
            log.info(
                "User %s is already a member of community %s, trying to accept existing invitation",
                user.id,
                community_role.community_id,
            )
            user_invitations_to_community = (
                db.session.query(MemberModel)
                .filter(
                    MemberModel.user_id == user.id,
                    MemberModel.community_id == community_role.community_id,
                )
                .all()
            )
            if len(user_invitations_to_community) == 1:
                if not user_invitations_to_community[0].active:
                    log.info(
                        "Found existing invitation for user %s, accepting it", user.id
                    )
                    current_communities.service.members.accept_invite(
                        system_identity, user_invitations_to_community[0].request_id
                    )
                else:
                    log.info(
                        "User %s is already a member of community %s, no action needed",
                        user.id,
                        community_role.community_id,
                    )
            else:
                log.error(
                    "User %s is already a member of community %s, but no unique invitation found. "
                    "Hits: %s",
                    user.id,
                    community_role.community_id,
                    user_invitations_to_community,
                )
                flash(
                    _(
                        "We could not add you to the community at this time. "
                        "Please log out of the repository, wait a few minutes and log in again. "
                        "If you will not become a member of the community, please contact the support."
                    ),
                    "error",
                )

    @classmethod
    def _remove_user_community_membership(cls, community_id: UUID, user: User) -> None:
        """Remove user from a community with a given role.

        :param community_id:        id of the community
        :param user:                user object
        :return:
        """
        data = {"members": [{"type": "user", "id": str(user.id)}]}
        log.info("Removing user %s from community %s", user.id, community_id)
        try:
            current_communities.service.members.delete(
                system_identity, community_id, data
            )
        except Exception as e:
            log.error(
                "Failed to remove user %s from community %s: %s",
                user.id,
                community_id,
                e,
            )
