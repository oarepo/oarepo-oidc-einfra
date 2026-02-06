#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
from __future__ import annotations

import datetime


def test_create_non_existing_group(smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id):
    with smart_record("test_create_group.yaml") as _recorded:
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )
        assert "id" in group

        assert group_created is True
        assert admin_created is True


def test_create_existing_group(smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id):
    with smart_record("test_create_group_existing.yaml"):
        _group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )
        assert not group_created
        assert not admin_created


def test_create_resource_for_group(
    smart_record,
    low_level_perun_api,
    test_repo_communities_id,
    test_group_id,
    test_vo_id,
    test_facility_id,
    test_capabilities_attribute_id,
    perun_sync_service_id,
):
    with smart_record("test_create_resource_for_group.yaml") as _recorded:
        resource, resource_created = low_level_perun_api.create_resource_with_group_and_capabilities(
            vo_id=test_vo_id,
            facility_id=test_facility_id,
            group_id=test_group_id,
            name="Community:AAA",
            description="Resource for community AAA",
            capability_attr_id=test_capabilities_attribute_id,
            capabilities=["res:communities:AAA"],
            perun_sync_service_id=perun_sync_service_id,
        )
        assert "id" in resource
        assert resource_created is True


def test_create_resource_for_group_existing(
    smart_record,
    low_level_perun_api,
    test_repo_communities_id,
    test_group_id,
    test_vo_id,
    test_facility_id,
    test_capabilities_attribute_id,
    perun_sync_service_id,
):
    with smart_record("test_create_resource_for_group_existing.yaml") as _recorded:
        resource, resource_created = low_level_perun_api.create_resource_with_group_and_capabilities(
            vo_id=test_vo_id,
            facility_id=test_facility_id,
            group_id=test_group_id,
            name="Community:AAA",
            description="Resource for community AAA",
            capability_attr_id=test_capabilities_attribute_id,
            capabilities=["res:communities:AAA"],
            perun_sync_service_id=perun_sync_service_id,
        )
        assert "id" in resource

        assert resource_created is False


def test_add_user_to_group(app, smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id):
    with smart_record("test_add_user_to_group.yaml") as constants:
        group, _group_created, _admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )

        user = low_level_perun_api.get_user_by_attribute(
            attribute_name=app.config["EINFRA_USER_ID_SEARCH_ATTRIBUTE"],
            attribute_value=constants.sample_user_einfra_id,
        )

        low_level_perun_api.add_user_to_group(vo_id=test_vo_id, group_id=group["id"], user_id=user["id"])

        low_level_perun_api.remove_user_from_group(vo_id=test_vo_id, group_id=group["id"], user_id=user["id"])


def test_send_invitation(app, smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id):
    with smart_record("test_invite_user_to_group.yaml"):
        group, _group_created, _admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )

        low_level_perun_api.send_invitation(
            vo_id=test_vo_id,
            group_id=group["id"],
            email="test@test.com",
            full_name="Test Testovic",
            language="en",
            expiration=(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=5)).date().isoformat(),
            redirect_url="https://example.com/invitation-accepted/123456",
        )


def test_replace_resource_capability(
    smart_record,
    low_level_perun_api,
    test_vo_id,
    test_facility_id,
    test_capabilities_attribute_id,
):
    """Test replacing a resource capability.

    This test verifies that:
    1. A resource can be found by its old capability
    2. The capability is replaced correctly
    3. The setAttribute API is called with the correct payload containing the new capability
    """
    from unittest.mock import patch

    with smart_record("test_replace_resource_capability.yaml") as recorded:
        # Get resource by old capability
        resource = low_level_perun_api.get_resource_by_capability(
            vo_id=test_vo_id,
            facility_id=test_facility_id,
            capability="res:communities:AAA",
        )
        assert resource is not None
        assert "id" in resource

        # Spy on _perun_call to capture the setAttribute payload
        # This allows us to verify the exact payload sent to Perun API
        original_perun_call = low_level_perun_api._perun_call
        setAttribute_calls = []

        def perun_call_spy(manager, method, payload):
            result = original_perun_call(manager, method, payload)
            if manager == "attributesManager" and method == "setAttribute":
                setAttribute_calls.append(payload)
            return result

        with patch.object(
            low_level_perun_api, "_perun_call", side_effect=perun_call_spy
        ):
            # Replace capability from AAA to BBB
            low_level_perun_api.patch_resource_capabilities(
                resource_id=resource["id"],
                capabilities_attribute_id=test_capabilities_attribute_id,
                remove=["res:communities:AAA"],
                add=["res:communities:BBB"],
            )

        # Verify setAttribute was called exactly once with the correct payload
        assert (
            len(setAttribute_calls) == 1
        ), "setAttribute should be called exactly once"
        set_attr_payload = setAttribute_calls[0]

        # Verify the payload contains the correct resource ID
        assert set_attr_payload["resource"] == resource["id"]

        # Verify the attribute object is present and contains the new capability
        assert "attribute" in set_attr_payload
        assert set_attr_payload["attribute"]["value"] == [
            "res:communities:BBB"
        ], "The new capability should replace the old one"
