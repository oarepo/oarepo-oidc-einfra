# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for update_user_entitlements()."""

from __future__ import annotations

import logging
import uuid

import pytest
from invenio_audit_logs.records.api import AuditLog
from invenio_communities.members.records.models import CommunityMetadata, MemberModel
from invenio_db import db

from oarepo_oidc_einfra.models import EInfraUserEntitlements
from oarepo_oidc_einfra.perun.entitlements import (
    CommunityEntitlement,
    GlobalRoleEntitlement,
    update_user_entitlements,
)


@pytest.fixture
def user(app, database):
    """Create a fresh user for update_user_entitlements tests."""
    from invenio_accounts.proxies import current_datastore

    new_user = current_datastore.create_user(
        email=f"{uuid.uuid4().hex}@example.org",
        password="not-used",  # noqa S106
        active=True,
    )
    current_datastore.commit()

    return new_user


def _membership(community_id, user_id):
    return db.session.query(MemberModel).filter_by(community_id=community_id, user_id=user_id).first()


def _stored_entitlements(user_id):
    row = db.session.query(EInfraUserEntitlements).filter_by(user_id=user_id).first()
    return set(row.entitlements) if row is not None else None


def _audit_log_actions(user_id):
    return [log.action for log in db.session.query(AuditLog.model_cls).filter_by(user_id=str(user_id)).all()]


def _member_entitlement(slug):
    return CommunityEntitlement.from_slug(
        entitlement=f"urn:geant:cesnet.cz:res:communities:{slug}:role:member#perun.cesnet.cz",
        community_slug=slug,
        role="member",
    )


def _curator_entitlement(slug):
    return CommunityEntitlement.from_slug(
        entitlement=f"urn:geant:cesnet.cz:res:communities:{slug}:role:curator#perun.cesnet.cz",
        community_slug=slug,
        role="curator",
    )


def _admin_entitlement():
    return GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )


def test_first_call_applies_all_new_entitlements_and_stores_them(app, communities, roles, user, search_clear):
    member = _member_entitlement("test-community")
    admin = _admin_entitlement()

    update_user_entitlements(user, {member, admin}, cause="first-login")

    membership = _membership(member.community.id, user.id)
    assert membership is not None
    assert membership.role == "member"
    assert admin.role in user.roles
    assert _stored_entitlements(user.id) == {member.entitlement, admin.entitlement}

    # the cause propagates all the way down to the persisted audit log entries
    assert sorted(_audit_log_actions(user.id)) == ["community.member_added", "role.member_added"]


def test_no_entitlements_and_no_prior_record_stores_nothing(app, user):
    update_user_entitlements(user, set(), cause="test")

    assert _stored_entitlements(user.id) is None


def test_repeated_call_with_same_entitlements_is_idempotent(app, communities, user, search_clear):
    member = _member_entitlement("test-community")

    update_user_entitlements(user, {member}, cause="test")
    update_user_entitlements(user, {member}, cause="test")

    members = db.session.query(MemberModel).filter_by(community_id=member.community.id, user_id=user.id).all()
    assert len(members) == 1
    assert members[0].role == "member"
    assert _stored_entitlements(user.id) == {member.entitlement}


def test_removes_entitlements_that_are_no_longer_present(app, communities, roles, user, search_clear):
    member = _member_entitlement("test-community")
    admin = _admin_entitlement()

    update_user_entitlements(user, {member, admin}, cause="grant")
    update_user_entitlements(user, {member}, cause="revoke-admin")

    assert _membership(member.community.id, user.id) is not None
    assert admin.role not in user.roles
    assert _stored_entitlements(user.id) == {member.entitlement}

    removal_logs = (
        db.session.query(AuditLog.model_cls).filter_by(user_id=str(user.id), action="role.member_removed").all()
    )
    assert len(removal_logs) == 1
    assert removal_logs[0].json["metadata"]["cause"] == "revoke-admin"
    assert removal_logs[0].json["resource"]["id"] == "administration"


def test_adds_new_entitlements_alongside_existing_ones(app, communities, roles, user, search_clear):
    member = _member_entitlement("test-community")
    admin = _admin_entitlement()

    update_user_entitlements(user, {member}, cause="test")
    update_user_entitlements(user, {member, admin}, cause="test")

    assert _membership(member.community.id, user.id) is not None
    assert admin.role in user.roles
    assert _stored_entitlements(user.id) == {member.entitlement, admin.entitlement}


def test_removing_all_entitlements_clears_membership_role_and_deletes_stored_record(
    app, communities, roles, user, search_clear
):
    member = _member_entitlement("test-community")
    admin = _admin_entitlement()

    update_user_entitlements(user, {member, admin}, cause="test")
    update_user_entitlements(user, set(), cause="test")

    assert _membership(member.community.id, user.id) is None
    assert admin.role not in user.roles
    # the user had entitlements before and now has none - the stored record is deleted,
    # not left behind with stale content
    assert _stored_entitlements(user.id) is None


def test_same_community_conflicting_roles_resolved_by_sort_key_order(app, communities, user, search_clear):
    member = _member_entitlement("test-community")
    curator = _curator_entitlement("test-community")

    # both entitlements share the same core ("community", "test-community"), so
    # they are deduplicated by sort_key (highest wins) before being applied and
    # stored - curator has the higher sort_key, so it wins over member.
    update_user_entitlements(user, {member, curator}, cause="test")

    membership = _membership(member.community.id, user.id)
    assert membership is not None
    assert membership.role == "curator"
    assert _stored_entitlements(user.id) == {curator.entitlement}


def test_changing_community_role_removes_old_and_applies_new(app, communities, user, search_clear):
    curator = _curator_entitlement("test-community")
    member = _member_entitlement("test-community")

    update_user_entitlements(user, {curator}, cause="test")
    update_user_entitlements(user, {member}, cause="test")

    members = db.session.query(MemberModel).filter_by(community_id=curator.community.id, user_id=user.id).all()
    assert len(members) == 1
    assert members[0].role == "member"
    assert _stored_entitlements(user.id) == {member.entitlement}


def test_apply_failure_for_one_entitlement_does_not_prevent_others_or_raise(app, communities, user, search_clear):
    doomed = _member_entitlement("test-community")
    good = _member_entitlement("another-community")

    # Corrupt the in-memory community reference held by "doomed" so that its
    # apply() raises a real (not mocked) error when it tries to query using
    # the community id - this happens synchronously, inside apply() itself.
    real_community_id = doomed.community.id
    doomed.community.id = "not-a-real-uuid"
    db.session.expunge(doomed.community)

    update_user_entitlements(user, {doomed, good}, cause="test")

    assert _membership(real_community_id, user.id) is None
    assert _membership(good.community.id, user.id) is not None
    # storage of the new entitlement set happens regardless of individual apply failures
    assert _stored_entitlements(user.id) == {doomed.entitlement, good.entitlement}


def test_stored_entitlement_referencing_deleted_community_is_ignored(
    app, communities, database, user, search_clear, caplog
):
    community = CommunityMetadata(slug="temporary-community")
    db.session.add(community)
    db.session.commit()

    stale = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:temporary-community:role:member#perun.cesnet.cz",
        community_slug="temporary-community",
        role="member",
    )
    update_user_entitlements(user, {stale}, cause="test")

    db.session.delete(community)
    db.session.commit()

    new_member = _member_entitlement("test-community")

    # the stored entitlement now references a deleted community - re-parsing it
    # should not raise, it should just be ignored (as if it was never known)
    with caplog.at_level(logging.DEBUG, logger="perun.entitlements"):
        update_user_entitlements(user, {new_member}, cause="test")

    assert _membership(new_member.community.id, user.id) is not None
    assert _stored_entitlements(user.id) == {new_member.entitlement}

    # "Unknown community" is a plain EntitlementException (not a bad-type one), so it
    # is logged at info, not debug
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("temporary-community" in m for m in info_messages)
    assert not any("temporary-community" in m for m in debug_messages)


def test_stored_entitlement_referencing_deleted_role_is_ignored(app, communities, user, search_clear):
    from invenio_accounts.proxies import current_datastore

    role = current_datastore.create_role(name="temporary-role")
    current_datastore.commit()

    stale = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:temporary-role#perun.cesnet.cz",
        role="temporary-role",
    )
    update_user_entitlements(user, {stale}, cause="test")

    db.session.delete(role)
    db.session.commit()

    new_member = _member_entitlement("test-community")

    # the stored entitlement now references a deleted role - re-parsing it
    # should not raise, it should just be ignored (as if it was never known)
    update_user_entitlements(user, {new_member}, cause="test")

    assert _membership(new_member.community.id, user.id) is not None
    assert _stored_entitlements(user.id) == {new_member.entitlement}


def test_stored_entitlement_with_unrecognized_type_is_ignored_and_logged_at_debug(
    app, communities, database, user, search_clear, caplog
):
    member = _member_entitlement("test-community")
    update_user_entitlements(user, {member}, cause="test")

    # sneak in a stored entitlement whose type we do not recognize at all (bypassing
    # the normal update_user_entitlements()/from_string() validation), simulating e.g.
    # a Perun group entitlement that ended up stored in an earlier version of the code
    row = db.session.query(EInfraUserEntitlements).filter_by(user_id=user.id).one()
    bad_type_urn = "urn:geant:cesnet.cz:res:testing_nrp_devel#perun.cesnet.cz"
    row.entitlements = [*row.entitlements, bad_type_urn]
    db.session.commit()

    with caplog.at_level(logging.DEBUG, logger="perun.entitlements"):
        update_user_entitlements(user, {member}, cause="test")

    assert _stored_entitlements(user.id) == {member.entitlement}

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("testing_nrp_devel" in m for m in debug_messages)
    assert not any("testing_nrp_devel" in m for m in info_messages)


def test_empty_update_with_only_unparseable_known_entitlements_leaves_stale_record(
    app, communities, database, user, search_clear
):
    community = CommunityMetadata(slug="temporary-community-2")
    db.session.add(community)
    db.session.commit()

    stale = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:temporary-community-2:role:member#perun.cesnet.cz",
        community_slug="temporary-community-2",
        role="member",
    )
    update_user_entitlements(user, {stale}, cause="test")

    db.session.delete(community)
    db.session.commit()

    # known_entitlements ends up empty (the only stored entry fails to parse and is
    # ignored) and new_entitlements is also empty - since we can't tell whether the
    # user genuinely has no entitlements or the stored record is merely corrupted,
    # the stale stored record is left untouched rather than deleted
    update_user_entitlements(user, set(), cause="test")

    assert _stored_entitlements(user.id) == {stale.entitlement}
