#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI (perun) communities mapping."""

import re

from invenio_access.permissions import Identity
from invenio_communities.communities.records.api import Community
from invenio_records_resources.services.records.components.base import ServiceComponent
from invenio_records_resources.services.uow import Operation, UnitOfWork

from oarepo_oidc_einfra.proxies import current_einfra_oidc


class PropagateToAAIOp(Operation):
    """Operation to propagate community to AAI in a background process."""

    def __init__(self, community: Community):
        """Create a new operation."""
        self.community = community

    def on_post_commit(self, uow: UnitOfWork) -> None:
        """Propagate the community to AAI.

        :param uow: unit of work
        """
        from oarepo_oidc_einfra.tasks import synchronize_community_to_perun

        synchronize_community_to_perun.delay(str(self.community.id))


class CommunityAAIComponent(ServiceComponent):
    """Community AAI component that propagates the community to Perun."""

    def create(
        self,
        identity: Identity,
        *,
        record: Community,
        data: dict,
        **kwargs: dict,
    ) -> None:
        """Create handler.

        This handler schedules the community to be propagated to AAI if the configuration
        (EINFRA_COMMUNITY_SYNCHRONIZATION) allows it.

        :param identity: identity of the user
        :param record: community record to be created
        :param data: data to be created
        :param kwargs: additional arguments
        """
        # propagate the community to AAI
        assert data is not None

        if "slug" not in data:
            raise ValueError("Missing slug in community data")
        if not re.match("^[a-z0-9-]+$", data["slug"]):
            raise ValueError(
                "Invalid slug, only lowercase letters, numbers and hyphens are allowed"
            )

        if current_einfra_oidc.synchronization_enabled:
            self.uow.register(PropagateToAAIOp(record))

    def update(
        self,
        identity: Identity,
        *,
        record: Community,
        data: dict,
        **kwargs: dict,
    ) -> None:
        """Update handler.

        This handler prevents changing community slug as it is used as a key in AAI capabilities.

        :param identity: identity of the user
        :param record: community record to be updated
        :param data: data to be updated
        :param kwargs: additional arguments
        """
        assert data is not None
        assert record is not None

        if record.slug != data["slug"]:
            raise ValueError(
                "Cannot change the slug of the community as it is used in AAI"
            )

    def delete(self, identity: Identity, *, record: Community, **kwargs: dict) -> None:
        """Delete handler.

        At this time, we do not want to delete communities in AAI, so we raise an error.

        :param identity: identity of the user
        :param record: community record to be deleted
        :param kwargs: additional arguments
        """
        raise NotImplementedError("Delete is not supported at the time being")
