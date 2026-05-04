#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""OIDC utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from urnparse import URN8141, InvalidURNFormatError

from ..communities import CommunityRole, CommunitySupport
from ..proxies import current_einfra_oidc
from .mapping import (
    SlugCommunityRole,
    parse_community_capability,
    parse_global_role_capability,
)

if TYPE_CHECKING:
    from collections.abc import Generator


log = logging.getLogger(__name__)


def get_communities_from_userinfo_token(userinfo_token: dict) -> set[CommunityRole]:
    """Extract communities and roles from userinfo token.

    :param userinfo_token:          userinfo token from perun/oidc server
    :return:                        a set of community roles associated with the user
    """
    cs = CommunitySupport()

    slug_to_id = cs.slug_to_id

    community_roles = cs.role_names

    aai_groups = set()
    for entitlement_mapping_part, urn in iter_mapping_entitlements(userinfo_token):
        slug_role: SlugCommunityRole | None = parse_community_capability(entitlement_mapping_part)
        if slug_role is None:
            continue
        if slug_role.role not in community_roles:
            log.error(
                "Role %s not found in community roles in urn %s",
                slug_role.role,
                urn,
            )
            continue
        if slug_role.slug not in slug_to_id:
            # if it is not in slug_to_id, the community for that slug does not exist
            # yet in invenio - an administrator should create it first.
            # This might happen if the community is created manually in perun
            # but is not yet created in invenio
            log.warning(
                "Community %s not found for urn %s",
                slug_role.slug,
                urn,
            )
            continue

        aai_groups.add(CommunityRole(slug_to_id[slug_role.slug], slug_role.role))

    return aai_groups


def iter_mapping_entitlements(
    userinfo_token: dict,
) -> Generator[tuple[list[str], URN8141]]:
    """Iterate over entitlements in userinfo token.

    :param userinfo_token:  userinfo token
    :return:                generator of entitlements
    """
    # Entitlement looks like:
    # 1 = {str} 'urn:geant:cesnet.cz:res:communities:cuni:role:curator#perun.cesnet.cz'
    entitlements = userinfo_token.get("eduperson_entitlement", [])
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
        yield parts[1:], urn


def get_global_roles_from_userinfo_token(userinfo_token: dict) -> set[str]:
    """Extract global roles from userinfo token.

    :param userinfo_token:  userinfo token
    :return:                set of global roles
    """
    global_roles = set()
    for entitlement_mapping_part, _urn in iter_mapping_entitlements(userinfo_token):
        global_role: str | None = parse_global_role_capability(entitlement_mapping_part)
        if global_role:
            global_roles.add(global_role)

    return global_roles
