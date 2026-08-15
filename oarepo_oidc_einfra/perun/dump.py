# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Dump data from the PERUN."""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from functools import cached_property
from typing import TYPE_CHECKING

from flask import current_app
from invenio_accounts.models import User, UserIdentity
from invenio_db import db

from oarepo_oidc_einfra.perun.entitlements import Entitlement

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger("perun.dump_data")


@dataclasses.dataclass(frozen=True)
class AAIUser:
    """A user with their roles as received from the Perun AAI."""

    user: User
    einfra_id: str
    email: str
    full_name: str
    organization: str
    entitlements: set[Entitlement]


class PerunDumpData:
    """Provides access to the data from the PERUN dump."""

    def __init__(
        self,
        dump_data: dict,
    ):
        """Create an instance of the data.

        :param dump_data:               The data from the PERUN dump (json)
        """
        self.dump_data = dump_data

    def users(self) -> Iterable[AAIUser]:
        """Return an iterable of all users from the dump."""
        for u in self.dump_data["users"].values():
            einfra_id = u["attributes"].get(
                current_app.config["EINFRA_USER_ID_DUMP_ATTRIBUTE"],
            )
            user = (
                db.session.query(User)
                .join(UserIdentity, UserIdentity.id_user == User.id)
                .filter(UserIdentity.id == einfra_id, UserIdentity.method == "e-infra")
            ).one_or_none()
            if user is None:
                continue

            full_name = u["attributes"].get(current_app.config["EINFRA_USER_DISPLAY_NAME_ATTRIBUTE"])
            organization = u["attributes"].get(current_app.config["EINFRA_USER_ORGANIZATION_ATTRIBUTE"])
            email = u["attributes"].get(current_app.config["EINFRA_USER_PREFERRED_MAIL_ATTRIBUTE"])
            yield AAIUser(
                user=user,
                einfra_id=einfra_id,
                email=email,
                full_name=full_name,
                organization=organization,
                entitlements=self.entitlements_for_resources(u.get("allowed_resources", {})),
            )

    @cached_property
    def resource_entitlements(self) -> dict[str, list[Entitlement]]:
        """Returns a mapping of resource id to entitlements.

        :return:    for each Perun resource, mapping to associated community roles
        """
        resources = defaultdict(list)
        for r_id, r in self.dump_data["resources"].items():
            # data look like
            # "0003a30a-5512-4ff1-ae1c-b13372041459" : {
            #   attributes" : {
            #       "urn:perun:resource:attribute-def:def:capabilities" : [
            #           res:communities:abc:role:members"
            capabilities = r.get("attributes", {}).get(current_app.config["EINFRA_CAPABILITIES_ATTRIBUTE_NAME"], [])
            for capability in capabilities:
                try:
                    # Get the first (and typically only) namespace from the set
                    namespace = next(iter(current_app.config["EINFRA_ENTITLEMENT_NAMESPACES"]))
                    resources[r_id].append(
                        Entitlement.from_string(
                            # we need to add missing namespace & prefix to the entitlement
                            # so that we can match it later on when user logs in
                            f"urn:{namespace}:{current_app.config['EINFRA_ENTITLEMENT_PREFIX']}:{capability}"
                        )
                    )
                except ValueError:
                    continue

        return resources

    def entitlements_for_resources(self, resource_ids: Iterable[str]) -> set[Entitlement]:
        """Return a mapping of resource id to entitlements."""
        entitlements = set()
        for r_id in resource_ids:
            entitlements.update(self.resource_entitlements.get(r_id, []))
        return entitlements
