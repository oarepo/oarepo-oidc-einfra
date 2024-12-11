#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Mapping between perun capabilities and Invenio roles."""

import dataclasses
from typing import Dict, Optional

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


def get_invenio_role_from_capability(capability: str | list) -> SlugCommunityRole:
    """Get the Invenio role from the capability.

    :param capability:      capability name
    :return:                (slug, role)
    """
    parts = capability.split(":") if isinstance(capability, str) else capability

    if (
        len(parts) == 5
        and parts[0] == "res"
        and parts[1] == "communities"
        and parts[3] == "role"
    ):
        return SlugCommunityRole(parts[2], parts[4])
    raise ValueError(f"Not an invenio role capability: {capability}")


def get_user_einfra_id(user_id: int) -> Optional[str]:
    """Get e-infra identity for user with given id.

    :param user_id:     user id
    :return:            e-infra identity or None if user has no e-infra identity associated
    """
    user_identity = UserIdentity.query.filter_by(
        id_user=user_id, method="e-infra"
    ).one_or_none()
    if user_identity:
        return user_identity.id
    return None


def einfra_to_local_users_map() -> Dict[str, int]:
    """Return a mapping of e-infra id to user id for local users.

     Only users that have e-infra identity and logged at least once with it re returned

    :return:                    a mapping of e-infra id to user id
    """
    local_users = {}
    rows = db.session.execute(  # type: ignore
        select(UserIdentity.id, UserIdentity.id_user).where(
            UserIdentity.method == "e-infra"
        )
    )
    for row in rows:
        einfra_id = row[0]
        user_id = row[1]
        if einfra_id:
            local_users[einfra_id] = user_id
    return local_users
