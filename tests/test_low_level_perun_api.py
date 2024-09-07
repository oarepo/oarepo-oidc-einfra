#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
def test_create_non_existing_group(
    smart_record, low_level_perun_api, test_repo_communities_id
):

    with smart_record("test_create_group.yaml") as recorded:
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
        )
        if recorded:
            assert group["id"] == 15883
        else:
            print(f"Add the >>> assert group['id'] == {group['id']} here <<<")

        assert group_created == True
        assert admin_created == True


def test_create_existing_group(
    smart_record, low_level_perun_api, test_repo_communities_id
):

    with smart_record("test_create_group_existing.yaml"):
        group, group_created, admin_created = low_level_perun_api.create_group(
            name="AAA",
            description="Community AAA",
            parent_group_id=test_repo_communities_id,
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
        if recorded:
            assert resource["id"] == 14408
        else:
            print(f"Add the >>> assert resource['id'] == {resource['id']} here <<<")
        assert resource_created == True


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
        if recorded:
            assert resource["id"] == 14408
        else:
            print(f"Add the >>> assert resource['id'] == {resource['id']} here <<<")

        assert resource_created == False
