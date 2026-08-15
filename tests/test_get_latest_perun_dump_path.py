# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for get_latest_perun_dump_path."""

from __future__ import annotations

import pytest

from oarepo_oidc_einfra.tasks import get_latest_perun_dump_path


def test_raises_when_bucket_has_no_dump_files(unique_s3_bucket):
    """Test that an empty bucket raises a ValueError."""
    with pytest.raises(ValueError, match="No perun dump files found"):
        get_latest_perun_dump_path()


def test_ignores_non_json_files(unique_s3_bucket):
    """Test that files not ending in .json are not considered dump files."""
    client, bucket_name = unique_s3_bucket
    client.put_object(Bucket=bucket_name, Key="not-a-dump.txt", Body=b"hello")

    with pytest.raises(ValueError, match="No perun dump files found"):
        get_latest_perun_dump_path()


def test_returns_the_most_recently_modified_json_file(unique_s3_bucket):
    """Test that the .json key with the latest LastModified timestamp wins."""
    import time

    client, bucket_name = unique_s3_bucket
    client.put_object(Bucket=bucket_name, Key="older.json", Body=b"{}")
    time.sleep(1.1)  # ensure a distinct, later LastModified timestamp
    client.put_object(Bucket=bucket_name, Key="newer.json", Body=b"{}")

    assert get_latest_perun_dump_path() == "newer.json"


def test_ignores_non_json_files_even_if_more_recent(unique_s3_bucket):
    """Test that a more recently modified non-.json file does not shadow a .json dump."""
    import time

    client, bucket_name = unique_s3_bucket
    client.put_object(Bucket=bucket_name, Key="dump.json", Body=b"{}")
    time.sleep(1.1)
    client.put_object(Bucket=bucket_name, Key="metadata.txt", Body=b"not a dump")

    assert get_latest_perun_dump_path() == "dump.json"


def test_paginates_through_all_objects(app, monkeypatch):
    """Test that list_objects_v2 pagination (ContinuationToken) is followed to completion.

    Uses a mocked S3 client rather than real MinIO pages, since producing enough real
    objects to trigger pagination (the default page size is 1000) would be impractical.
    """
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    first_page = {
        "Contents": [{"Key": "page1.json", "LastModified": datetime(2024, 1, 1, tzinfo=timezone.utc)}],
        "NextContinuationToken": "token-1",
    }
    second_page = {
        "Contents": [{"Key": "page2.json", "LastModified": datetime(2024, 6, 1, tzinfo=timezone.utc)}],
    }
    mock_client.list_objects_v2.side_effect = [first_page, second_page]
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: mock_client)

    result = get_latest_perun_dump_path()

    assert result == "page2.json"
    assert mock_client.list_objects_v2.call_count == 2
    first_call_kwargs = mock_client.list_objects_v2.call_args_list[0].kwargs
    assert "ContinuationToken" not in first_call_kwargs
    second_call_kwargs = mock_client.list_objects_v2.call_args_list[1].kwargs
    assert second_call_kwargs["ContinuationToken"] == "token-1"
