#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
from invenio_communities.members.services.request import CommunityInvitation
from oarepo_runtime.i18n import lazy_gettext as _


class AAICommunityInvitation(CommunityInvitation):
    type_id = "aai-community-invitation"
    name = _("AAI Community invitation")

    # there is no invenio receiver for this type as it is handled by the AAI
    receiver_can_be_none = True
    allowed_receiver_ref_types = []
