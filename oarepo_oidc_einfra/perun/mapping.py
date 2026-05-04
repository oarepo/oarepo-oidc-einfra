#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Mapping between perun capabilities and Invenio roles."""

from __future__ import annotations

import dataclasses

from invenio_accounts.models import UserIdentity
from invenio_db import db
from sqlalchemy import select


def get_perun_capability_from_invenio_role(slug: str, role: str) -> str:
    """Get the capability name from the Invenio role.

    :param slug:        slug of the community
    :param role:        role in the community
    :return:            capability name
    """
    return f"res:communities:{slug}:role:{role}"


@dataclasses.dataclass
class SlugCommunityRole:
    """A class representing a community slug and a role."""

    slug: str
    """Community slug."""

    role: str
    """Role name."""


# res:communities:{slug}:role:{role}
COMMUNITY_CAPABILITY_PARTS_COUNT = 5

# res:roles:{role}
GLOBAL_ROLE_CAPABILITY_PARTS_COUNT = 3


def parse_community_capability(
    capability: str | list[str] | tuple[str, ...],
) -> SlugCommunityRole | None:
    """Try to parse a capability as a community role.

    :param capability:      capability name
    :return:                SlugCommunityRole if the capability matches the
                            ``res:communities:{slug}:role:{role}`` pattern,
                            ``None`` otherwise
    """
    parts = capability.split(":") if isinstance(capability, str) else capability

    if (
        len(parts) == COMMUNITY_CAPABILITY_PARTS_COUNT
        and parts[0] == "res"
        and parts[1] == "communities"
        and parts[3] == "role"
    ):
        return SlugCommunityRole(parts[2], parts[4])
    return None


def parse_global_role_capability(
    capability: str | list[str] | tuple[str, ...],
) -> str | None:
    """Try to parse a capability as a global role.

    :param capability:      capability name
    :return:                role if the capability matches the
                            ``res:global:role:{role}`` pattern, ``None`` otherwise
    """
    parts = capability.split(":") if isinstance(capability, str) else capability
    if len(parts) == GLOBAL_ROLE_CAPABILITY_PARTS_COUNT and parts[0] == "res" and parts[1] == "roles":
        return parts[2]
    return None


def get_user_einfra_id(user_id: int) -> str | None:
    """Get e-infra identity for user with given id.

    :param user_id:     user id
    :return:            e-infra identity or None if user has no e-infra identity associated
    """
    user_identity = UserIdentity.query.filter_by(id_user=user_id, method="e-infra").one_or_none()
    if user_identity and user_identity.id:
        return str(user_identity.id)
    return None


def einfra_to_local_users_map() -> dict[str, int]:
    """Return a mapping of e-infra id to user id for local users.

     Only users that have e-infra identity and logged at least once with it re returned

    :return:                    a mapping of e-infra id to user id
    """
    local_users = {}
    rows = db.session.execute(select(UserIdentity.id, UserIdentity.id_user).where(UserIdentity.method == "e-infra"))
    for row in rows:
        einfra_id = row[0]
        user_id = row[1]
        if einfra_id:
            local_users[einfra_id] = user_id
    return local_users
