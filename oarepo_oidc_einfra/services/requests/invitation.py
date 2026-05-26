#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI backed invitation request."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from invenio_communities.members.services.request import CommunityInvitation
from invenio_i18n import lazy_gettext as _
from marshmallow import fields
from oarepo_requests.types import DefaultReceiverMixin

if TYPE_CHECKING:
    from flask_principal import Identity
    from invenio_records.api import Record


class AAICommunityInvitation(DefaultReceiverMixin, CommunityInvitation):
    """AAI backed invitation request."""

    type_id = "aai-community-invitation"
    name = _("AAI Community invitation")  # type: ignore[reportAssignmentType]

    # there is no invenio receiver for this type as it is handled by the AAI
    receiver_can_be_none = True
    allowed_receiver_ref_types: ClassVar[list[str]] = []  # type: ignore[reportIncompatibleVariableOverride]

    payload_schema: ClassVar[dict] = {  # type: ignore[reportIncompatibleVariableOverride]
        # Identifier of the invitation request from the AAI system
        "aai_id": fields.String(),
        "user": fields.Integer(),
    }

    @override
    @classmethod
    def default_request_receiver(
        cls,
        identity: Identity,
        topic: Record,
        creator: dict[str, str] | Identity,
        data: dict,
    ) -> dict[str, str] | None:
        return None
