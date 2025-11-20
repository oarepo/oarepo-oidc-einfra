#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI backed invitation request."""

from __future__ import annotations

from typing import ClassVar

from invenio_communities.members.services.request import CommunityInvitation
from invenio_i18n import lazy_gettext as _
from marshmallow import fields


class AAICommunityInvitation(CommunityInvitation):
    """AAI backed invitation request."""

    type_id = "aai-community-invitation"
    name = _("AAI Community invitation")  # type: ignore[reportAssignmentType]

    # there is no invenio receiver for this type as it is handled by the AAI
    receiver_can_be_none = True
    allowed_receiver_ref_types: ClassVar[list[str]] = []  # type: ignore[reportIncompatibleVariableOverride]

    payload_schema: ClassVar[dict] = {  # type: ignore[reportIncompatibleVariableOverride]
        # Identifier of the invitation request from the AAI system
        "aai_id": fields.String(),
    }
