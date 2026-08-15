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

    app_config["EINFRA_USER_DUMP_S3_ACCESS_KEY"] = "invenio"
    app_config["EINFRA_USER_DUMP_S3_SECRET_KEY"] = "invenio8"  # noqa S105
    app_config["EINFRA_USER_DUMP_S3_ENDPOINT"] = "http://localhost:9000"
    app_config["EINFRA_USER_DUMP_S3_BUCKET"] = "dump"

    app_config["EINFRA_CAPABILITIES_ATTRIBUTE_NAME"] = "urn:perun:resource:attribute-def:def:capabilities"

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


@pytest.fixture(scope="module")
def e_infra_dump(app, database):
    """Create S3 bucket and upload the e-infra dump file for testing.

    Creates the bucket specified in EINFRA_USER_DUMP_S3_BUCKET if it doesn't exist,
    and uploads the dump.json file from the tests directory if one doesn't already exist.
    """
    import json
    from pathlib import Path
    import json

    import boto3
    from flask import current_app

    # Create S3 client
    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )

    bucket_name = current_app.config["EINFRA_USER_DUMP_S3_BUCKET"]

    # Create bucket if it doesn't exist
    try:
        client.head_bucket(Bucket=bucket_name)
    except client.exceptions.ClientError:
        # Bucket doesn't exist, create it
        client.create_bucket(Bucket=bucket_name)

    # Check if dump.json already exists
    try:
        client.head_object(Bucket=bucket_name, Key="dump.json")
        # File exists, nothing to do
        return
    except client.exceptions.ClientError:
        # File doesn't exist, upload empty dump
        pass

    # Upload dump file from tests/dump.json
    dump_path = Path(__file__).parent / "minimal_dump.json"
    with dump_path.open("rb") as f:
        dump_content = f.read()

    client.put_object(
        Bucket=bucket_name,
        Key="dump.json",
        Body=dump_content,
        ContentType="application/json",
    )
