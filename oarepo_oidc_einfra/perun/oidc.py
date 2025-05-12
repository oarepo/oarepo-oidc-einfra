#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""OIDC utilities."""

import logging
from typing import Set

from urnparse import URN8141, InvalidURNFormatError

from ..communities import CommunityRole, CommunitySupport
from ..proxies import current_einfra_oidc
from .mapping import SlugCommunityRole, get_invenio_role_from_capability

log = logging.getLogger(__name__)


def get_communities_from_userinfo_token(userinfo_token: dict) -> Set[CommunityRole]:
    """Extract communities and roles from userinfo token.

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
        if urn.namespace_id.value not in current_einfra_oidc.entitlement_namespaces:
            continue
        parts = urn.specific_string.parts
        if not parts or parts[0] != current_einfra_oidc.entitlement_prefix:
            continue
        try:
            slug_role: SlugCommunityRole = get_invenio_role_from_capability(parts[1:])
            if slug_role.role not in community_roles:
                log.error(
                    f"Role {slug_role.role} not found in community roles in urn {urn}"
                )
                continue
            if slug_role.slug not in slug_to_id:
                # if it is not in slug_to_id, the community for that slug does not exist
                # yet in invenio - an administrator should create it first.
                # This might happen if the community is created manually in perun
                # but is not yet created in invenio
                continue

            aai_groups.add(CommunityRole(slug_to_id[slug_role.slug], slug_role.role))
        except ValueError:
            continue

    return aai_groups
