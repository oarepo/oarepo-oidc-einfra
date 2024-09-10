#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""OIDC utilities."""
from typing import Set

from flask import current_app
from urnparse import URN8141, InvalidURNFormatError

from .mapping import get_invenio_role_from_capability
from ..communities import CommunityRole, CommunitySupport
import logging

log = logging.getLogger(__name__)


def get_communities_from_userinfo_token(userinfo_token) -> Set[CommunityRole]:
    """
    Extracts communities and roles from userinfo token.

    :param userinfo_token:          userinfo token from perun/oidc server
    :return:                        a set of community roles associated with the user
    """
    cs = CommunitySupport()

    slug_to_id = cs.slug_to_id

    community_roles = cs.role_names

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
        parts = urn.specific_string.parts
        if not parts or parts[0] != current_app.config["EINFRA_ENTITLEMENT_PREFIX"]:
            continue
        try:
            community_slug, role = get_invenio_role_from_capability(parts[1:])
            if role not in community_roles:
                log.error(f"Role {role} not found in community roles in urn {urn}")
                continue
            aai_groups.add((slug_to_id[community_slug], role))
        except ValueError:
            continue

    return aai_groups
