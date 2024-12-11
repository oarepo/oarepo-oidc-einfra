#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

import datetime


def test_create_non_existing_group(
    smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id
):
    with smart_record("test_create_group.yaml") as recorded:
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )
        assert "id" in group

        assert group_created is True
        assert admin_created is True


def test_create_existing_group(
    smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id
):
    with smart_record("test_create_group_existing.yaml"):
        group, group_created, admin_created = low_level_perun_api.create_group(
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
    with smart_record("test_create_resource_for_group.yaml") as recorded:
        resource, resource_created = (
            low_level_perun_api.create_resource_with_group_and_capabilities(
                vo_id=test_vo_id,
                facility_id=test_facility_id,
                group_id=test_group_id,
                name="Community:AAA",
                description="Resource for community AAA",
                capability_attr_id=test_capabilities_attribute_id,
                capabilities=["res:communities:AAA"],
                perun_sync_service_id=perun_sync_service_id,
            )
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
    with smart_record("test_create_resource_for_group_existing.yaml") as recorded:
        resource, resource_created = (
            low_level_perun_api.create_resource_with_group_and_capabilities(
                vo_id=test_vo_id,
                facility_id=test_facility_id,
                group_id=test_group_id,
                name="Community:AAA",
                description="Resource for community AAA",
                capability_attr_id=test_capabilities_attribute_id,
                capabilities=["res:communities:AAA"],
                perun_sync_service_id=perun_sync_service_id,
            )
        )
        assert "id" in resource

        assert resource_created is False


def test_add_user_to_group(
    app, smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id
):
    with smart_record("test_add_user_to_group.yaml") as constants:
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )

        user = low_level_perun_api.get_user_by_attribute(
            attribute_name=app.config["EINFRA_USER_ID_SEARCH_ATTRIBUTE"],
            attribute_value=constants.sample_user_einfra_id,
        )

        low_level_perun_api.add_user_to_group(
            vo_id=test_vo_id, group_id=group["id"], user_id=user["id"]
        )

        low_level_perun_api.remove_user_from_group(
            vo_id=test_vo_id, group_id=group["id"], user_id=user["id"]
        )


def test_send_invitation(
    app, smart_record, low_level_perun_api, test_repo_communities_id, test_vo_id
):
    with smart_record("test_invite_user_to_group.yaml"):
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
            parent_vo=test_vo_id,
        )

        low_level_perun_api.send_invitation(
            vo_id=test_vo_id,
            group_id=group["id"],
            email="test@test.com",
            fullName="Test Testovic",
            language="en",
            expiration=(datetime.datetime.now() + datetime.timedelta(days=5))
            .date()
            .isoformat(),
            redirect_url="https://example.com/invitation-accepted/123456",
        )
