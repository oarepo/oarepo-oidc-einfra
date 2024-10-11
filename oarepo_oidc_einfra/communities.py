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
from functools import cached_property
from typing import TYPE_CHECKING, Iterable

from flask import current_app
from invenio_access.permissions import system_identity
from invenio_communities.communities.records.api import Community
from invenio_communities.members.errors import AlreadyMemberError
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from marshmallow import ValidationError
from sqlalchemy import select
from sqlalchemy.sql.expression import true

if TYPE_CHECKING:
    from uuid import UUID

    from invenio_accounts.models import User

log = logging.getLogger(__name__)


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
            for row in db.session.execute(
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

        for community_role in new_community_roles - current_community_roles:
            cls._add_user_community_membership(community_role, user)

        for v in new_community_roles:
            assert isinstance(v, CommunityRole)

        print("Current community roles ", current_community_roles)
        print("New community roles ", new_community_roles)

        community_ids = {
            r.community_id for r in current_community_roles - new_community_roles
        }
        for community_id in community_ids:
            try:
                cls._remove_user_community_membership(community_id, user)
            except ValidationError as e:
                # This is a case when the user is the last member of a community - in this case he can not be removed
                current_app.logger.error(
                    f"Failed to remove user {user.id} from community {community_id}: {e}"
                )

    @classmethod
    def get_user_community_membership(cls, user: User) -> set[CommunityRole]:
        """Get user's actual community roles.

        :param user: User object
        """
        ret = set()
        for row in db.session.execute(
            select([MemberModel.community_id, MemberModel.role]).where(
                MemberModel.user_id == user.id, MemberModel.active == true()
            )
        ):
            ret.add(CommunityRole(row.community_id, row.role))

        return ret

    @classmethod
    def get_user_list_community_membership(
        cls, user_ids: Iterable[int]
    ) -> dict[int, set[CommunityRole]]:
        """Get community roles of a list of users.

        :param user_ids: List of user ids
        """
        ret: dict[int, set[CommunityRole]] = {}
        for row in db.session.execute(
            select(
                [MemberModel.community_id, MemberModel.user_id, MemberModel.role]
            ).where(MemberModel.user_id.in_(user_ids), MemberModel.active == true())
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
        try:
            return current_communities.service.members.add(
                system_identity, community_role.community_id, data
            )
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
            results = current_communities.service.members.search_invitations(
                system_identity,
                community_role.community_id,
                params={"user.id": str(user.id)},
            )
            hits = list(results.hits)
            if len(hits) == 1:
                current_communities.service.members.accept_invitation(
                    system_identity, hits[0]["request_id"]
                )

    @classmethod
    def _remove_user_community_membership(cls, community_id: UUID, user: User) -> None:
        """Remove user from a community with a given role.

        :param community_id:        id of the community
        :param user:                user object
        :return:
        """
        data = {"members": [{"type": "user", "id": str(user.id)}]}
        current_communities.service.members.delete(system_identity, community_id, data)
