# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for parsing community and role entitlements from PERUN dump."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from invenio_accounts.models import UserIdentity
from invenio_db import db

from oarepo_oidc_einfra.perun.dump import AAIUser, PerunDumpData
from oarepo_oidc_einfra.perun.entitlements import (
    CommunityEntitlement,
    GlobalRoleEntitlement,
)


@pytest.fixture(scope="module")
def minimal_dump_data(app):
    """Load the minimal dump JSON file for testing."""
    dump_path = Path(__file__).parent.parent / "minimal_dump.json"
    with dump_path.open("rb") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def perun_dump_data(minimal_dump_data, communities, roles):
    """Create a PerunDumpData instance from minimal dump data.

    Depends on communities and roles fixtures to ensure they are created first,
    since entitlement parsing requires them to exist in the database.
    """
    return PerunDumpData(minimal_dump_data)


@pytest.fixture(scope="module")
def users_with_identities(app, database):
    """Create users with matching e-infra identities for testing.

    Creates four users corresponding to the users in MINIMAL_DUMP_WITH_COMMUNITY_AND_ROLE:
    - test-user-id@einfra.cesnet.cz (has community + role entitlements)
    - community-user-id@einfra.cesnet.cz (has only community entitlements)
    - role-user-id@einfra.cesnet.cz (has only role entitlements)
    - noentitlements-user-id@einfra.cesnet.cz (has no valid entitlements)
    """
    from invenio_accounts.proxies import current_datastore

    user_ids = [
        "test-user-id@einfra.cesnet.cz",
        "community-user-id@einfra.cesnet.cz",
        "role-user-id@einfra.cesnet.cz",
        "noentitlements-user-id@einfra.cesnet.cz",
    ]

    users = []
    for einfra_id in user_ids:
        user = current_datastore.create_user(
            email=f"user-{einfra_id.split('@')[0]}@example.com",
            password="not-used",  # noqa S106
            active=True,
        )
        # Commit to get the user ID before creating identity
        current_datastore.commit()

        identity = UserIdentity(
            id=einfra_id,
            id_user=user.id,
            method="e-infra",
        )
        db.session.add(identity)
        users.append((user, einfra_id))

    database.session.commit()

    return {einfra_id: user for user, einfra_id in users}


class TestCommunityEntitlements:
    """Tests for parsing community entitlements from dump data."""

    def test_resource_entitlements_include_community_roles(self, perun_dump_data, communities):
        """Test that resources with community capabilities are parsed correctly."""
        resource_entitlements = perun_dump_data.resource_entitlements

        # Check test-community member entitlement
        assert "resource-for-test-community-member" in resource_entitlements
        entitlements = resource_entitlements["resource-for-test-community-member"]
        assert len(entitlements) == 1
        ent = entitlements[0]
        assert isinstance(ent, CommunityEntitlement)
        assert ent.community_slug == "test-community"
        assert ent.role == "member"

        # Check another-community curator entitlement
        assert "resource-for-another-community-curator" in resource_entitlements
        entitlements = resource_entitlements["resource-for-another-community-curator"]
        assert len(entitlements) == 1
        ent = entitlements[0]
        assert isinstance(ent, CommunityEntitlement)
        assert ent.community_slug == "another-community"
        assert ent.role == "curator"

    def test_invalid_community_resources_are_skipped(self, perun_dump_data):
        """Test that resources with unknown communities are skipped during parsing."""
        resource_entitlements = perun_dump_data.resource_entitlements

        # Resource with nonexistent community should not have any entitlements
        assert "resource-with-invalid-community" in resource_entitlements
        assert resource_entitlements["resource-with-invalid-community"] == []

    def test_user_with_multiple_community_entitlements(
        self, perun_dump_data, users_with_identities, communities
    ):
        """Test that a user with multiple community entitlements gets all of them."""
        users = list(perun_dump_data.users())

        # Find the user with only community entitlements
        community_user = None
        for u in users:
            if u.einfra_id == "community-user-id@einfra.cesnet.cz":
                community_user = u
                break

        assert community_user is not None
        assert isinstance(community_user, AAIUser)

        entitlements = community_user.entitlements
        assert len(entitlements) == 2

        entitlement_strings = {str(e) for e in entitlements}
        expected = {
            "urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
            "urn:geant:cesnet.cz:res:communities:another-community:role:curator#perun.cesnet.cz",
        }
        assert entitlement_strings == expected

    def test_user_entitlements_match_allowed_resources(
        self, perun_dump_data, users_with_identities, communities
    ):
        """Test that user entitlements correctly reflect their allowed_resources."""
        users = list(perun_dump_data.users())

        # Find the user with both community and role entitlements
        test_user = None
        for u in users:
            if u.einfra_id == "test-user-id@einfra.cesnet.cz":
                test_user = u
                break

        assert test_user is not None

        # Should have 3 entitlements: 2 community + 1 global role
        entitlements = test_user.entitlements
        assert len(entitlements) == 3

        entitlement_strings = {str(e) for e in entitlements}
        assert "urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz" in entitlement_strings
        assert "urn:geant:cesnet.cz:res:communities:another-community:role:curator#perun.cesnet.cz" in entitlement_strings
        assert "urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz" in entitlement_strings


class TestRoleEntitlements:
    """Tests for parsing global role entitlements from dump data."""

    def test_resource_entitlements_include_global_roles(self, perun_dump_data, roles):
        """Test that resources with role capabilities are parsed correctly."""
        resource_entitlements = perun_dump_data.resource_entitlements

        # Check administration role entitlement
        assert "resource-for-admin-role" in resource_entitlements
        entitlements = resource_entitlements["resource-for-admin-role"]
        assert len(entitlements) == 1
        ent = entitlements[0]
        assert isinstance(ent, GlobalRoleEntitlement)
        assert ent.role_name == "administration"

    def test_user_with_only_role_entitlements(
        self, perun_dump_data, users_with_identities, roles
    ):
        """Test that a user with only role entitlements gets them correctly."""
        users = list(perun_dump_data.users())

        # Find the user with only role entitlements
        role_user = None
        for u in users:
            if u.einfra_id == "role-user-id@einfra.cesnet.cz":
                role_user = u
                break

        assert role_user is not None
        assert isinstance(role_user, AAIUser)

        entitlements = role_user.entitlements
        assert len(entitlements) == 1

        ent = list(entitlements)[0]
        assert isinstance(ent, GlobalRoleEntitlement)
        assert ent.role_name == "administration"

    def test_user_with_no_valid_entitlements_has_empty_set(
        self, perun_dump_data, users_with_identities
    ):
        """Test that a user with only invalid resources has no entitlements."""
        users = list(perun_dump_data.users())

        # Find the user with no valid entitlements
        no_entitlements_user = None
        for u in users:
            if u.einfra_id == "noentitlements-user-id@einfra.cesnet.cz":
                no_entitlements_user = u
                break

        assert no_entitlements_user is not None
        assert isinstance(no_entitlements_user, AAIUser)

        # Should have empty entitlements set since the only resource maps to unknown community
        assert no_entitlements_user.entitlements == set()


class TestEntitlementsForResources:
    """Tests for the entitlements_for_resources method."""

    def test_returns_correct_entitlements_for_single_resource(
        self, perun_dump_data, communities, roles
    ):
        """Test getting entitlements for a single resource ID."""
        entitlements = perun_dump_data.entitlements_for_resources(
            ["resource-for-test-community-member"]
        )
        assert len(entitlements) == 1
        ent = list(entitlements)[0]
        assert isinstance(ent, CommunityEntitlement)
        assert ent.community_slug == "test-community"
        assert ent.role == "member"

    def test_returns_combined_entitlements_for_multiple_resources(
        self, perun_dump_data, communities, roles
    ):
        """Test getting entitlements for multiple resource IDs."""
        resource_ids = [
            "resource-for-test-community-member",
            "resource-for-another-community-curator",
            "resource-for-admin-role",
        ]
        entitlements = perun_dump_data.entitlements_for_resources(resource_ids)
        assert len(entitlements) == 3

        entitlement_strings = {str(e) for e in entitlements}
        assert "urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz" in entitlement_strings
        assert "urn:geant:cesnet.cz:res:communities:another-community:role:curator#perun.cesnet.cz" in entitlement_strings
        assert "urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz" in entitlement_strings

    def test_returns_empty_set_for_nonexistent_resources(self, perun_dump_data):
        """Test getting entitlements for non-existent resource IDs."""
        entitlements = perun_dump_data.entitlements_for_resources(
            ["nonexistent-resource-1", "nonexistent-resource-2"]
        )
        assert entitlements == set()

    def test_handles_mixed_valid_invalid_resources(self, perun_dump_data, communities, roles):
        """Test getting entitlements when some resources are valid and others are not."""
        resource_ids = [
            "resource-for-test-community-member",  # Valid
            "resource-with-invalid-community",  # Invalid community
            "nonexistent-resource",  # Doesn't exist
        ]
        entitlements = perun_dump_data.entitlements_for_resources(resource_ids)
        # Only the valid resource should contribute entitlements
        assert len(entitlements) == 1
        assert str(list(entitlements)[0]) == "urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz"
