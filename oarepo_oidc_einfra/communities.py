#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Helper functions for working with communities."""
from collections import namedtuple
from functools import cached_property
from typing import Dict, Set

from flask import current_app
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_communities.communities.records.api import Community
from invenio_communities.members.errors import AlreadyMemberError
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from marshmallow import ValidationError
from sqlalchemy import select

CommunityRole = namedtuple("CommunityRole", ["community_id", "role"])
"""A named tuple representing a community and a role."""


class CommunitySupport:
    """A support class for working with communities and their members."""

    def __init__(self):
        pass

    @cached_property
    def slug_to_id(self) -> Dict[str, str]:
        """
        Returns a mapping of community slugs to their ids.
        """
        return {
            row[1]: str(row[0])
            for row in db.session.execute(
                select(Community.model_cls.id, Community.model_cls.slug)
            )
        }

    @cached_property
    def all_community_roles(self) -> Set[CommunityRole]:
        """
        Returns a set of all community roles (pair of community id, role name) known to the repository.

        :return:                    a set of all community roles known to the repository
        """
        repository_comunity_roles = set()
        community_roles = self.role_names

        for community in Community.model_cls.query.all():
            for role in community_roles:
                repository_comunity_roles.add(CommunityRole(community.id, role))
        return repository_comunity_roles

    @cached_property
    def role_names(self) -> Set[str]:
        """
        Returns a set of all known community role names, as configured inside the invenio.cfg
        :return:                a set of all known community role names
        """
        return {role["name"] for role in current_app.config["COMMUNITIES_ROLES"]}

    @classmethod
    def set_user_community_membership(
        cls, user: User, new_community_roles: Set[CommunityRole]
    ) -> None:
        """Set user membership based on the new community roles.

        The previous community roles, not present in new_community_roles, are removed.
        """
        current_community_roles = cls.get_user_community_membership(user)

        for community_id, role in new_community_roles - current_community_roles:
            cls._add_user_community_membership(community_id, role, user)

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
    def get_user_community_membership(cls, user) -> Set[CommunityRole]:
        """Get user's actual community roles.

        :param user: User object
        """
        ret = set()
        for row in db.session.execute(
            select([MemberModel.community_id, MemberModel.role]).where(
                MemberModel.user_id == user.id, MemberModel.active == True
            )
        ):
            ret.add(CommunityRole(row.community_id, row.role))

        return ret

    @classmethod
    def _add_user_community_membership(
        cls, community_id: str, community_role: str, user: User
    ) -> None:
        """
        Add user to a community with a given role.

        :param community_id:            id of the community
        :param community_role:          community role
        :param user:                    user object
        :return:                        A membership result item from service
        """
        data = {
            "role": community_role,
            "members": [{"type": "user", "id": str(user.id)}],
        }
        try:
            return current_communities.service.members.add(
                system_identity, community_id, data
            )
        except AlreadyMemberError as e:
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
                system_identity, community_id, params={"user.id": str(user.id)}
            )
            hits = list(results.hits)
            if len(hits) != 1:
                raise AlreadyMemberError(
                    f"User {user.id} is already an inactive member of community {community_id} but there is no or multiple invitations. "
                    f"This should never happen. Invitations: {hits}"
                )
            current_communities.service.members.accept_invitation(
                system_identity, hits[0]["request_id"]
            )

    @classmethod
    def _remove_user_community_membership(cls, community_id, user) -> None:
        """
        Remove user from a community with a given role.

        :param community_id:        id of the community
        :param user:                user object
        :return:
        """
        data = {"members": [{"type": "user", "id": str(user.id)}]}
        current_communities.service.members.delete(system_identity, community_id, data)
