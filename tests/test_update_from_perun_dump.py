# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for the update_from_perun_dump celery task."""

from __future__ import annotations

import hashlib
import json

from oarepo_oidc_einfra.tasks import update_from_perun_dump


def _community_user_profile(users_with_identities):
    community_user = users_with_identities["community-user-id@einfra.cesnet.cz"]
    return community_user, community_user.user_profile or {}


def test_does_nothing_when_dump_disabled(app, monkeypatch):
    """Test that the task returns immediately when dump support is disabled, without touching S3."""
    from flask import current_app

    monkeypatch.setattr(current_app.extensions["einfra-oidc"], "dump_enabled", False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("boto3.client should not be called when dump support is disabled")

    monkeypatch.setattr("oarepo_oidc_einfra.tasks.boto3.client", fail_if_called)

    # should not raise, and should not touch S3 at all
    update_from_perun_dump(dump_path="whatever.json")


def test_downloads_and_syncs_from_explicit_dump_path(
    unique_s3_bucket, minimal_dump_json, users_with_identities, communities, roles, search_clear
):
    """Test that a given dump_path is downloaded and used to synchronize users."""
    client, bucket_name = unique_s3_bucket
    content = json.dumps(minimal_dump_json).encode("utf-8")
    client.put_object(Bucket=bucket_name, Key="explicit-dump.json", Body=content)

    update_from_perun_dump(dump_path="explicit-dump.json")

    community_user, user_profile = _community_user_profile(users_with_identities)
    assert user_profile.get("full_name") == "Community User"
    assert community_user.email == "community@example.com"


def test_finds_and_downloads_latest_dump_when_no_path_given(
    unique_s3_bucket, minimal_dump_json, users_with_identities, communities, roles, search_clear
):
    """Test that the task looks up the latest dump in S3 when dump_path is not given."""
    import time

    client, bucket_name = unique_s3_bucket
    content = json.dumps(minimal_dump_json).encode("utf-8")
    # an older, unrelated .json file that should be ignored in favor of the newer one
    client.put_object(Bucket=bucket_name, Key="older.json", Body=b'{"metadata": {}, "resources": {}, "users": {}}')
    time.sleep(1.1)
    client.put_object(Bucket=bucket_name, Key="latest.json", Body=content)

    update_from_perun_dump()

    community_user, user_profile = _community_user_profile(users_with_identities)
    assert user_profile.get("full_name") == "Community User"
    assert community_user.email == "community@example.com"


def test_checksum_mismatch_aborts_without_syncing(unique_s3_bucket, minimal_dump_json, users_with_identities):
    """Test that a wrong checksum prevents the dump from being processed."""
    client, bucket_name = unique_s3_bucket
    content = json.dumps(minimal_dump_json).encode("utf-8")
    client.put_object(Bucket=bucket_name, Key="dump.json", Body=content)

    community_user, profile_before = _community_user_profile(users_with_identities)
    email_before = community_user.email

    update_from_perun_dump(dump_path="dump.json", checksum="0" * 64)

    _, profile_after = _community_user_profile(users_with_identities)
    assert profile_after == profile_before
    assert community_user.email == email_before


def test_checksum_match_syncs(
    unique_s3_bucket, minimal_dump_json, users_with_identities, communities, roles, search_clear
):
    """Test that a correct checksum allows the dump to be processed."""
    client, bucket_name = unique_s3_bucket
    content = json.dumps(minimal_dump_json).encode("utf-8")
    client.put_object(Bucket=bucket_name, Key="dump.json", Body=content)
    checksum = hashlib.sha256(content).hexdigest()

    update_from_perun_dump(dump_path="dump.json", checksum=checksum)

    community_user, user_profile = _community_user_profile(users_with_identities)
    assert user_profile.get("full_name") == "Community User"
    assert community_user.email == "community@example.com"
