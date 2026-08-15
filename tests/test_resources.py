# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for the OIDC e-infra REST API resources.

These routes are registered as ``invenio_base.api_blueprints``, so they only exist on the
API application (``invenio_app.factory.create_api``), not the default UI application used
by the rest of the test suite - hence the ``create_app`` override below, which pytest-invenio
picks up automatically for this module (see ``base_app`` in pytest_invenio.fixtures).
"""

from __future__ import annotations

import hashlib
import json

import pytest
from invenio_accounts.testutils import create_test_user, login_user_via_session
from invenio_app.factory import create_api

# resources.py registers its routes as invenio_base.api_blueprints, which only get mounted on
# the API application - so this module needs to use create_api instead of the default (UI)
# create_app fixture from conftest.py. pytest-invenio picks up this module-level attribute
# automatically (see base_app in pytest_invenio.fixtures); it must be a plain function, not a
# @pytest.fixture, since base_app looks it up via getattr() rather than fixture resolution.
create_app = create_api


@pytest.fixture
def user_with_permission(app, database):
    """Create a user with the upload-oidc-einfra-dump permission."""
    import uuid

    from invenio_access.models import ActionUsers
    from invenio_db import db

    from oarepo_oidc_einfra.resources import upload_dump_action

    # unique email per call - the module-scoped database fixture is not rolled back between
    # tests, so a fixed email would collide once more than one test requests this fixture
    user = create_test_user(email=f"uploader-{uuid.uuid4().hex}@example.org")
    db.session.add(ActionUsers.allow(upload_dump_action, user_id=user.id))
    db.session.commit()
    return user


@pytest.fixture
def user_without_permission(app, database):
    """Create a user that is logged in but lacks the upload-oidc-einfra-dump permission."""
    import uuid

    return create_test_user(email=f"no-permission-{uuid.uuid4().hex}@example.org")


@pytest.fixture
def mocked_dump_task(monkeypatch):
    """Replace update_from_perun_dump.delay with a recorder, so resource tests don't run a real sync."""
    import oarepo_oidc_einfra.resources as resources_module

    calls = []
    monkeypatch.setattr(
        resources_module.update_from_perun_dump,
        "delay",
        lambda dump_path, checksum: calls.append((dump_path, checksum)),
    )
    return calls


def test_upload_dump_requires_login(client):
    """Test that an anonymous request is rejected."""
    response = client.post("/auth/oidc/einfra/dumps/upload", data=b"{}", content_type="application/json")
    assert response.status_code in (401, 302)


def test_upload_dump_requires_permission(client, user_without_permission):
    """Test that a logged in user without the upload permission gets a 403."""
    login_user_via_session(client, user=user_without_permission)

    response = client.post("/auth/oidc/einfra/dumps/upload", data=b"{}", content_type="application/json")
    assert response.status_code == 403


def test_upload_dump_requires_json_content_type(client, user_with_permission):
    """Test that a non-JSON request body is rejected before anything is stored."""
    login_user_via_session(client, user=user_with_permission)

    response = client.post("/auth/oidc/einfra/dumps/upload", data=b"not json", content_type="text/plain")

    assert response.status_code == 400
    assert response.json["status"] == "error"


def test_upload_dump_stores_dump_and_triggers_sync(client, user_with_permission, unique_s3_bucket, mocked_dump_task):
    """Test that a successful upload stores the body in S3 and schedules the sync task."""
    login_user_via_session(client, user=user_with_permission)
    s3_client, bucket_name = unique_s3_bucket

    body = json.dumps({"hello": "world"}).encode("utf-8")
    response = client.post("/auth/oidc/einfra/dumps/upload", data=body, content_type="application/json")

    assert response.status_code == 201
    assert response.json == {"status": "ok"}

    # the sync task should have been scheduled with the stored path and a matching checksum
    assert len(mocked_dump_task) == 1
    dump_path, checksum = mocked_dump_task[0]
    assert checksum == hashlib.sha256(body).hexdigest()

    # and the body should really be sitting in S3 under that path
    stored = s3_client.get_object(Bucket=bucket_name, Key=dump_path)
    assert stored["Body"].read() == body


def test_upload_dump_remembers_last_dump_path_in_cache(
    client, user_with_permission, unique_s3_bucket, mocked_dump_task
):
    """Test that the stored dump path is cached under EINFRA_LAST_DUMP_PATH."""
    from invenio_cache.proxies import current_cache

    login_user_via_session(client, user=user_with_permission)

    body = b'{"a": 1}'
    response = client.post("/auth/oidc/einfra/dumps/upload", data=body, content_type="application/json")
    assert response.status_code == 201

    dump_path, _ = mocked_dump_task[0]
    assert current_cache.cache.get("EINFRA_LAST_DUMP_PATH") == dump_path


def test_notify_dump_requires_login(client):
    """Test that an anonymous request is rejected."""
    response = client.post("/auth/oidc/einfra/dumps/notify")
    assert response.status_code in (401, 302)


def test_notify_dump_requires_permission(client, user_without_permission):
    """Test that a logged in user without the upload permission gets a 403."""
    login_user_via_session(client, user=user_without_permission)

    response = client.post("/auth/oidc/einfra/dumps/notify")
    assert response.status_code == 403


def test_notify_dump_triggers_sync_with_configured_last_dump_path(
    client, user_with_permission, mocked_dump_task, app
):
    """Test that notify schedules the sync task for EINFRA_LAST_DUMP_PATH, without a checksum."""
    login_user_via_session(client, user=user_with_permission)

    response = client.post("/auth/oidc/einfra/dumps/notify")

    assert response.status_code == 201
    assert response.json == {"status": "ok"}
    assert mocked_dump_task == [(app.config["EINFRA_LAST_DUMP_PATH"], None)]
