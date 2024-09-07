#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""OIDC utilities."""
from typing import Dict, Set

from flask import current_app
from invenio_accounts.models import UserIdentity
from invenio_db import db
from sqlalchemy import select
from urnparse import URN8141, InvalidURNFormatError

from ..communities import CommunityRole, CommunitySupport


def get_communities_from_userinfo_token(userinfo_token) -> Set[CommunityRole]:
    """
    Extracts communities and roles from userinfo token.

    :param userinfo_token:          userinfo token from perun/oidc server
    :return:                        a set of community roles associated with the user
    """
    slug_to_id = CommunitySupport().slug_to_id

    community_roles = CommunitySupport().role_names

    # Entitlement looks like:
    # 1 = {str} 'urn:geant:cesnet.cz:res:communities:cuni:role:curator#perun.cesnet.cz'
    entitlements = userinfo_token.get("eduperson_entitlement", [])
    aai_groups = set()
    for entitlement in entitlements:
        try:
            urn = URN8141.from_string(entitlement)
        except InvalidURNFormatError:
            # not a valid URN, skipping
            continue
        if (
            urn.namespace_id.value
            not in current_app.config["EINFRA_ENTITLEMENT_NAMESPACES"]
        ):
            continue
        for group_parts in current_app.config[
            "EINFRA_ENTITLEMENT_COMMUNITIES_GROUP_PARTS"
        ]:
            if urn.specific_string.parts[: len(group_parts)] == group_parts and len(
                urn.specific_string.parts
            ) > len(group_parts):
                parts = urn.specific_string.parts[len(group_parts) :]
                if (
                    len(parts) == 3
                    and parts[0] in slug_to_id
                    and parts[2] in community_roles
                ):
                    aai_groups.add((slug_to_id[parts[0]], parts[2]))
    return aai_groups


def einfra_to_local_users_map() -> Dict[str, int]:
    """
    Returns a mapping of e-infra id to user id for local users, that have e-infra identity
    and logged at least once with it.

    :return:                    a mapping of e-infra id to user id
    """
    local_users = {}
    rows = db.session.execute(
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
