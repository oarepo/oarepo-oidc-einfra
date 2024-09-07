#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI (perun) communities mapping"""

import re

from flask import current_app
from invenio_records_resources.services.records.components.base import ServiceComponent
from invenio_records_resources.services.uow import Operation


class PropagateToAAIOp(Operation):
    """Operation to propagate community to AAI in a background process."""

    def __init__(self, community):
        self.community = community

    def on_post_commit(self, uow):
        from oarepo_oidc_einfra.tasks import synchronize_community_to_perun

        synchronize_community_to_perun.delay(self.community.id)


class CommunityAAIComponent(ServiceComponent):
    """Community AAI component that propagates the community to Perun."""

    def create(self, identity, record=None, data=None, **kwargs):
        """Create handler."""
        # propagate the community to AAI
        if "slug" not in data:
            raise ValueError("Missing slug in community data")
        if not re.match("^[a-z0-9-]+$", data["slug"]):
            raise ValueError(
                "Invalid slug, only lowercase letters, numbers and hyphens are allowed"
            )

        if current_app.config["EINFRA_COMMUNITY_SYNCHRONIZATION"]:
            self.uow.register(PropagateToAAIOp(record))

    def update(self, identity, record=None, data=None, **kwargs):
        """Update handler."""
        if record.slug != data["slug"]:
            raise ValueError(
                "Cannot change the slug of the community as it is used in AAI"
            )

    def delete(self, identity, record=None, **kwargs):
        """Delete handler."""
        raise NotImplementedError("Delete is not supported at the time being")
