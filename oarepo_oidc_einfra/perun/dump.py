#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
import dataclasses
import logging
from collections import defaultdict, namedtuple
from datetime import UTC, datetime
from functools import cached_property
from typing import Any, Dict, Iterable, List, Set

import boto3
from flask import current_app

from oarepo_oidc_einfra.communities import CommunityRole

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
    """
    Provides access to the data from the PERUN dump.
    """

    def __init__(
        self,
        dump_data: Any,
        community_slug_to_id: Dict[str, str],
        community_role_names: Set[str],
    ):
        """
        Creates an instance of the data

        :param dump_data:               The data from the PERUN dump (json)
        :param community_slug_to_id:    Mapping of community slugs to their ids (str of uuid)
        :param community_role_names:         a set of known community role names
        """
        self.dump_data = dump_data
        self.slug_to_id = community_slug_to_id
        self.community_role_names = community_role_names

    @cached_property
    def aai_community_roles(self) -> Set[CommunityRole]:
        """
        Returns all community roles (pairs of community id, role name) from the dump.
        :return: set of community roles known to perun
        """
        aai_community_roles = set()
        for resource_community_roles in self.resource_to_community_roles.values():
            aai_community_roles.update(resource_community_roles)
        return aai_community_roles

    @cached_property
    def resource_to_community_roles(self) -> Dict[str, List[CommunityRole]]:
        """
        Returns a mapping of resource id to community roles.

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
                "urn:perun:resource:attribute-def:def:capabilities", []
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
                    community_role = CommunityRole(self.slug_to_id[community_slug], role)
                    resources[r_id].append(community_role)

        return resources

    def users(self) -> Iterable[AAIUser]:
        """
        Returns all users from the dump.

        :return: iterable of AAIUser
        """
        for u in self.dump_data["users"].values():
            einfra_id = u["attributes"].get(
                "urn:perun:user:attribute-def:virt:login-namespace:einfraid-persistent"
            )
            full_name = u["attributes"].get(
                "urn:perun:user:attribute-def:core:displayName"
            )
            organization = u["attributes"].get(
                "urn:perun:user:attribute-def:def:organization"
            )
            email = u["attributes"].get(
                "urn:perun:user:attribute-def:def:preferredMail"
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
        """
        Returns community roles for an iterable of allowed resources.

        :param allowed_resources:       iterable of resource ids
        :return:                        a set of associated community roles
        """
        aai_communities = set()
        for resource in allowed_resources:
            aai_communities.update(self.resource_to_community_roles.get(resource, []))
        return aai_communities


def import_dump_file(data: bytes) -> str:
    """
    Imports a dump file from the input stream into S3 and returns file name
    """
    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )
    now = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M-%S")
    dump_path = f"{now}.json"
    client.put_object(
        Bucket=current_app.config["EINFRA_USER_DUMP_S3_BUCKET"],
        Key=dump_path,
        Body=data,
    )
    return dump_path
