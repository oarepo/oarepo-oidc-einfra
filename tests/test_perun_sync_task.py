# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

from __future__ import annotations

from invenio_access.permissions import system_identity
from invenio_communities import current_communities

from oarepo_oidc_einfra.tasks import synchronize_community_to_perun


def test_sync_community(app, db, location, smart_record, search_clear):
    community = current_communities.service.create(
        system_identity,
        {
            "slug": "CUNI",
            "metadata": {
                "title": "Charles University",
                "description": "Charles university members",
            },
            "access": {"visibility": "public"},
        },
    )
    current_communities.service.indexer.refresh()

    with smart_record("test_initial_sync_community.yaml"):
        synchronize_community_to_perun(community.id)
