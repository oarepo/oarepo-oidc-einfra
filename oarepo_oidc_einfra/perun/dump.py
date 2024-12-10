#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Dump data from the PERUN."""

import dataclasses
import logging
from collections import defaultdict
from functools import cached_property
from typing import Dict, Iterable, List, Set
from uuid import UUID

from oarepo_oidc_einfra.communities import CommunityRole
from oarepo_oidc_einfra.proxies import current_einfra_oidc

log = logging.getLogger("perun.dump_data")


@dataclasses.dataclass(frozen=True)
class AAIUser:
    """A user with their roles as received from the Perun AAI."""

    einfra_id: str
    email: str
    full_name: str
    organization: str
    roles: Set[CommunityRole]


class PerunDumpData:
    """Provides access to the data from the PERUN dump."""

    def __init__(
        self,
        dump_data: dict,
        community_slug_to_id: Dict[str, UUID],
        community_role_names: Set[str],
    ):
        """Create an instance of the data.

        :param dump_data:               The data from the PERUN dump (json)
        :param community_slug_to_id:    Mapping of community slugs to their ids (str of uuid)
        :param community_role_names:         a set of known community role names
        """
        self.dump_data = dump_data
        self.slug_to_id = community_slug_to_id
        self.community_role_names = community_role_names

    @cached_property
    def aai_community_roles(self) -> Set[CommunityRole]:
        """Return all community roles from the dump.

        :return: set of community roles known to perun
        """
        aai_community_roles = set()
        for resource_community_roles in self.resource_to_community_roles.values():
            aai_community_roles.update(resource_community_roles)
        return aai_community_roles

    @cached_property
    def resource_to_community_roles(self) -> Dict[str, List[CommunityRole]]:
        """Returns a mapping of resource id to community roles.

        :return:    for each Perun resource, mapping to associated community roles
        """
        resources = defaultdict(list)
        for r_id, r in self.dump_data["resources"].items():
            # data look like
            # "0003a30a-5512-4ff1-ae1c-b13372041459" : {
            #   "attributes" : {
            #       "urn:perun:resource:attribute-def:def:capabilities" : [
            #           "res:communities:abc:role:members"
            #       ]
            #   }
            # },
            capabilities = r.get("attributes", {}).get(
                current_einfra_oidc.capabilities_attribute_name, []
            )
            for capability in capabilities:
                parts = capability.split(":")
                if (
                    len(parts) == 5
                    and parts[0] == "res"
                    and parts[1] == "communities"
                    and parts[3] == "role"
                ):
                    community_slug = parts[2]
                    role = parts[4]
                    if community_slug not in self.slug_to_id:
                        log.error(
                            f"Community from PERUN {community_slug} not found in the repository"
                        )
                        continue
                    if role not in self.community_role_names:
                        log.error(f"Role from PERUN {role} not found in the repository")
                        continue
                    community_role = CommunityRole(
                        self.slug_to_id[community_slug], role
                    )
                    resources[r_id].append(community_role)

        return resources

    def users(self) -> Iterable[AAIUser]:
        """Return all users from the dump.

        :return: iterable of AAIUser
        """
        for u in self.dump_data["users"].values():
            einfra_id = u["attributes"].get(
                current_einfra_oidc.einfra_user_id_dump_attribute,
            )
            full_name = u["attributes"].get(
                current_einfra_oidc.user_display_name_attribute
            )
            organization = u["attributes"].get(
                current_einfra_oidc.user_organization_attribute
            )
            email = u["attributes"].get(
                current_einfra_oidc.user_preferred_mail_attribute
            )
            yield AAIUser(
                einfra_id=einfra_id,
                email=email,
                full_name=full_name,
                organization=organization,
                roles=self._get_roles_for_resources(u.get("allowed_resources", {})),
            )

    def _get_roles_for_resources(
        self, allowed_resources: Iterable[str]
    ) -> Set[CommunityRole]:
        """Return community roles for an iterable of allowed resources.

        :param allowed_resources:       iterable of resource ids
        :return:                        a set of associated community roles
        """
        aai_communities = set()
        for resource in allowed_resources:
            aai_communities.update(self.resource_to_community_roles.get(resource, []))
        return aai_communities
