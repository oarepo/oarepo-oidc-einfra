# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for perun dump synchronization tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from invenio_audit_logs.records.api import AuditLog
from invenio_communities.members.records.models import CommunityMetadata, MemberModel
from invenio_db import db

from oarepo_oidc_einfra.models import EInfraUserEntitlements
from oarepo_oidc_einfra.perun.dump import PerunDumpData
from oarepo_oidc_einfra.tasks import synchronize_users_from_perun


@pytest.fixture(scope="module")
def minimal_dump_json(app):
    """Load the minimal dump JSON file content."""
    dump_path = Path(__file__).parent / "minimal_dump.json"
    with dump_path.open("rb") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def users_with_identities(app, database):
    """Create users with matching e-infra identities for testing.

    Creates four users corresponding to the users in minimal_dump.json:
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

        from invenio_accounts.models import UserIdentity

        identity = UserIdentity(
            id=einfra_id,
            id_user=user.id,
            method="e-infra",
        )
        db.session.add(identity)
        users.append((user, einfra_id))

    database.session.commit()

    return {einfra_id: user for user, einfra_id in users}


def _get_user_entitlements(user_id):
    """Get stored entitlements for a user."""
    row = db.session.query(EInfraUserEntitlements).filter_by(user_id=user_id).first()
    return set(row.entitlements) if row is not None else set()


def _get_community_memberships(user_id):
    """Get community memberships for a user."""
    return db.session.query(MemberModel).filter_by(user_id=user_id).all()


def _get_community_slug(community_id):
    """Get the slug of a community by its id."""
    return db.session.query(CommunityMetadata).filter_by(id=community_id).first().slug


def _get_user_roles(user_id):
    """Get global roles for a user."""
    from invenio_accounts.models import User

    user = db.session.query(User).get(user_id)
    return {role.name for role in user.roles} if user else set()


def _audit_logs(user_id, action=None):
    """Get persisted audit log entries for a user, optionally filtered by action."""
    query = db.session.query(AuditLog.model_cls).filter_by(user_id=str(user_id))
    if action is not None:
        query = query.filter_by(action=action)
    return query.all()


class TestSynchronizeUsersFromPerun:
    """Tests for the synchronize_users_from_perun function."""

    def test_synchronizes_user_metadata(self, minimal_dump_json, users_with_identities, communities, search_clear):
        """Test that user metadata is updated from the dump."""
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # Check that user metadata was updated
        community_user = users_with_identities["community-user-id@einfra.cesnet.cz"]
        user_profile = community_user.user_profile or {}

        assert user_profile.get("full_name") == "Community User"
        assert user_profile.get("affiliations") == "Test Org"
        assert community_user.email == "community@example.com"

    def test_assigns_community_entitlements(self, minimal_dump_json, users_with_identities, communities, search_clear):
        """Test that users get correct community memberships from the dump."""
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # Check user with only community entitlements
        community_user = users_with_identities["community-user-id@einfra.cesnet.cz"]
        memberships = _get_community_memberships(community_user.id)

        assert len(memberships) == 2

        slugs_roles = {(_get_community_slug(m.community_id), m.role) for m in memberships}
        assert ("test-community", "member") in slugs_roles
        assert ("another-community", "curator") in slugs_roles

        # Check stored entitlements
        entitlements = _get_user_entitlements(community_user.id)
        assert len(entitlements) == 2
        assert any("test-community" in e and "member" in e for e in entitlements)
        assert any("another-community" in e and "curator" in e for e in entitlements)

        # Check that each community membership was recorded in the audit log
        logs = _audit_logs(community_user.id, action="community.member_added")
        assert len(logs) == 2
        assert {log.json["metadata"]["cause"] for log in logs} == {"perun-dump-sync"}
        slugs_roles_from_logs = {(log.json["metadata"]["community_slug"], log.json["metadata"]["role"]) for log in logs}
        assert slugs_roles_from_logs == slugs_roles

    def test_assigns_role_entitlements(self, minimal_dump_json, users_with_identities, roles, search_clear):
        """Test that users get correct global roles from the dump."""
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # Check user with only role entitlements
        role_user = users_with_identities["role-user-id@einfra.cesnet.cz"]
        user_roles = _get_user_roles(role_user.id)

        assert "administration" in user_roles

        # Check stored entitlements
        entitlements = _get_user_entitlements(role_user.id)
        assert len(entitlements) == 1
        assert any("administration" in e for e in entitlements)

        # Check that the role grant was recorded in the audit log
        logs = _audit_logs(role_user.id, action="role.member_added")
        assert len(logs) == 1
        assert logs[0].json["resource"] == {"type": "role", "id": "administration"}
        assert logs[0].json["metadata"]["cause"] == "perun-dump-sync"

    def test_assigns_both_community_and_role_entitlements(
        self, minimal_dump_json, users_with_identities, communities, roles, search_clear
    ):
        """Test that users get both community and role entitlements."""
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # Check user with both types of entitlements
        test_user = users_with_identities["test-user-id@einfra.cesnet.cz"]

        # Should have community memberships
        memberships = _get_community_memberships(test_user.id)
        assert len(memberships) == 2

        slugs_roles = {(_get_community_slug(m.community_id), m.role) for m in memberships}
        assert ("test-community", "member") in slugs_roles
        assert ("another-community", "curator") in slugs_roles

        # Should have global role
        user_roles = _get_user_roles(test_user.id)
        assert "administration" in user_roles

        # Should have all three entitlements stored
        entitlements = _get_user_entitlements(test_user.id)
        assert len(entitlements) == 3

        # Should have an audit log entry for each of the three entitlements
        assert len(_audit_logs(test_user.id, action="community.member_added")) == 2
        assert len(_audit_logs(test_user.id, action="role.member_added")) == 1

    def test_user_with_no_valid_entitlements_has_empty_entitlements(
        self, minimal_dump_json, users_with_identities, search_clear
    ):
        """Test that users with only invalid resources get no entitlements."""
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # Check user with no valid entitlements
        no_ent_user = users_with_identities["noentitlements-user-id@einfra.cesnet.cz"]

        # Should have no community memberships
        memberships = _get_community_memberships(no_ent_user.id)
        assert len(memberships) == 0

        # Should have no global roles
        user_roles = _get_user_roles(no_ent_user.id)
        assert len(user_roles) == 0

        # Should have no stored entitlements
        entitlements = _get_user_entitlements(no_ent_user.id)
        assert entitlements == set()

        # And no audit log entries at all, since nothing was granted or revoked
        assert _audit_logs(no_ent_user.id) == []

    def test_removes_entitlements_for_users_not_in_dump(
        self, minimal_dump_json, users_with_identities, communities, roles, search_clear
    ):
        """Test that entitlements are removed for users no longer in the dump."""
        # Create a new user that's NOT in the dump but has entitlements
        from invenio_accounts.proxies import current_datastore
        from invenio_accounts.models import UserIdentity

        extra_user = current_datastore.create_user(
            email="extra-user@example.com",
            password="not-used",  # noqa S106
            active=True,
        )
        current_datastore.commit()

        extra_identity = UserIdentity(
            id="extra-user-id@einfra.cesnet.cz",
            id_user=extra_user.id,
            method="e-infra",
        )
        db.session.add(extra_identity)
        db.session.commit()

        # Give the extra user some entitlements *through* update_user_entitlements, so that
        # (like a real previous sync would) an EInfraUserEntitlements row is stored for them -
        # this is what makes synchronize_users_from_perun consider them a "known" user whose
        # entitlements need to be removed if they are no longer in the dump.
        from oarepo_oidc_einfra.perun.entitlements import (
            CommunityEntitlement,
            GlobalRoleEntitlement,
            update_user_entitlements,
        )

        admin_entitlement = GlobalRoleEntitlement.from_role_name(
            entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
            role="administration",
        )
        community_entitlement = CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
            community_slug="test-community",
            role="member",
        )
        update_user_entitlements(
            extra_user,
            {admin_entitlement, community_entitlement},
            cause="test-setup",
        )

        # Verify the extra user has the entitlements before syncing
        assert _get_user_roles(extra_user.id) == {"administration"}
        assert len(_get_community_memberships(extra_user.id)) == 1
        assert len(_get_user_entitlements(extra_user.id)) == 2
        assert len(_audit_logs(extra_user.id, action="role.member_added")) == 1
        assert len(_audit_logs(extra_user.id, action="community.member_added")) == 1

        # Sync with a dump that does not contain the extra user - their entitlements,
        # role and community membership should be removed.
        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        assert _get_user_roles(extra_user.id) == set()
        assert _get_community_memberships(extra_user.id) == []
        assert _get_user_entitlements(extra_user.id) == set()

        # Both removals should be recorded in the audit log with the removal cause
        role_removed_logs = _audit_logs(extra_user.id, action="role.member_removed")
        assert len(role_removed_logs) == 1
        assert role_removed_logs[0].json["resource"] == {"type": "role", "id": "administration"}
        assert role_removed_logs[0].json["metadata"]["cause"] == "perun-dump-user-removed"

        community_removed_logs = _audit_logs(extra_user.id, action="community.member_removed")
        assert len(community_removed_logs) == 1
        assert community_removed_logs[0].json["resource"] == {"type": "community", "id": "test-community"}
        assert community_removed_logs[0].json["metadata"]["cause"] == "perun-dump-user-removed"

    def test_one_user_failure_does_not_prevent_syncing_other_users(
        self, minimal_dump_json, users_with_identities, communities, roles, search_clear, monkeypatch
    ):
        """Test that a database problem while syncing one user does not abort syncing the others.

        ``test-user-id`` is the *first* user in the dump, so this also verifies that the
        for-loop in ``synchronize_users_from_perun`` continues to later iterations after an
        earlier one fails, rather than the whole task aborting.
        """
        import oarepo_oidc_einfra.tasks as tasks_module

        test_user = users_with_identities["test-user-id@einfra.cesnet.cz"]
        original_update_user_entitlements = tasks_module.update_user_entitlements

        def failing_update_user_entitlements(user, entitlements, cause):
            if user.id == test_user.id:
                raise RuntimeError("simulated database failure")
            return original_update_user_entitlements(user, entitlements, cause)

        monkeypatch.setattr(tasks_module, "update_user_entitlements", failing_update_user_entitlements)

        # capture test_user's state before the (failing) sync - other tests in this module may
        # have already synced them, so we assert "unchanged by this call" rather than "empty"
        memberships_before = {(m.community_id, m.role) for m in _get_community_memberships(test_user.id)}
        roles_before = _get_user_roles(test_user.id)
        entitlements_before = _get_user_entitlements(test_user.id)

        dump = PerunDumpData(minimal_dump_json)
        # should not raise, despite test_user's update failing
        synchronize_users_from_perun(dump)

        # the failing user's entitlements should be untouched by this failed sync attempt
        memberships_after = {(m.community_id, m.role) for m in _get_community_memberships(test_user.id)}
        assert memberships_after == memberships_before
        assert _get_user_roles(test_user.id) == roles_before
        assert _get_user_entitlements(test_user.id) == entitlements_before

        # but the users processed after it in the dump should still be fully synced
        community_user = users_with_identities["community-user-id@einfra.cesnet.cz"]
        memberships = _get_community_memberships(community_user.id)
        slugs_roles = {(_get_community_slug(m.community_id), m.role) for m in memberships}
        assert slugs_roles == {("test-community", "member"), ("another-community", "curator")}

        role_user = users_with_identities["role-user-id@einfra.cesnet.cz"]
        assert _get_user_roles(role_user.id) == {"administration"}

        # the session should still be usable afterwards - the failure must not have left
        # a dangling/closed transaction behind
        no_ent_user = users_with_identities["noentitlements-user-id@einfra.cesnet.cz"]
        assert _get_user_entitlements(no_ent_user.id) == set()

    def test_does_not_create_users_without_matching_identity(self, minimal_dump_json, database, search_clear):
        """Test that users without matching identities are skipped."""
        # Get initial user count
        from invenio_accounts.models import User

        initial_count = db.session.query(User).count()

        dump = PerunDumpData(minimal_dump_json)
        synchronize_users_from_perun(dump)

        # User count should not increase (users in dump without identities are skipped)
        final_count = db.session.query(User).count()
        assert final_count == initial_count
