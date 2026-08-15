# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Test configuration and fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def create_app(instance_path, entry_points):
    """Application factory fixture."""
    from invenio_app.factory import create_app

    return create_app


@pytest.fixture(scope="module")
def app_config(app_config):
    """Configure test application."""
    app_config["CELERY_TASK_ALWAYS_EAGER"] = True
    app_config["CELERY_TASK_EAGER_PROPAGATES"] = True

    app_config["RECORDS_REFRESOLVER_CLS"] = "invenio_records.resolver.InvenioRefResolver"
    app_config["RECORDS_REFRESOLVER_STORE"] = "invenio_jsonschemas.proxies.current_refresolver_store"
    # Variable not used. We set it to silence warnings
    app_config["JSONSCHEMAS_HOST"] = "not-used"

    app_config["AUDIT_LOGS_ENABLED"] = True

    # Community roles for testing sort keys
    app_config["COMMUNITIES_ROLES"] = [
        {
            "name": "curator",
            "title": "Curator",
            "description": "Can curate records.",
            "can_manage": True,
            "is_owner": True,
            "can_manage_roles": ["member"],
        },
        {
            "name": "member",
            "title": "Member",
            "description": "Community member with read permissions.",
        },
    ]

    return app_config


@pytest.fixture(scope="module")
def communities(app, database, location):
    """Create communities used by entitlement tests, via the community service."""
    from invenio_access.permissions import system_identity
    from invenio_communities.proxies import current_communities

    service = current_communities.service
    communities = [
        service.create(
            system_identity,
            {
                "access": {
                    "visibility": "public",
                    "members_visibility": "public",
                    "member_policy": "open",
                    "record_submission_policy": "open",
                },
                "slug": slug,
                "metadata": {"title": slug},
            },
        )
        for slug in ("test-community", "another-community")
    ]
    database.session.commit()

    return communities


@pytest.fixture(scope="module")
def roles(app, database):
    """Create global roles used by entitlement tests."""
    from invenio_accounts.proxies import current_datastore

    role = current_datastore.create_role(name="administration")
    current_datastore.commit()

    return [role]
