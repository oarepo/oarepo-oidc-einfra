# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for the persisted (invenio-audit-logs) audit trail of entitlement changes."""

from __future__ import annotations

import uuid

import pytest
from invenio_audit_logs.records.api import AuditLog
from invenio_db import db
from invenio_db.uow import UnitOfWork

from oarepo_oidc_einfra.perun.entitlements import CommunityEntitlement, GlobalRoleEntitlement


@pytest.fixture
def user(app, database):
    """Create a fresh user for audit log tests."""
    from invenio_accounts.proxies import current_datastore

    new_user = current_datastore.create_user(
        email=f"{uuid.uuid4().hex}@example.org",
        password="not-used",  # noqa: S106
        active=True,
    )
    current_datastore.commit()

    return new_user


def _audit_logs(user_id, action=None):
    query = db.session.query(AuditLog.model_cls).filter_by(user_id=str(user_id))
    if action is not None:
        query = query.filter_by(action=action)
    return query.all()


def test_apply_new_community_membership_creates_audit_log(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "test-cause", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="community.member_added")
    assert len(logs) == 1
    assert logs[0].resource_type == "community"
    assert logs[0].json["resource"] == {"type": "community", "id": "test-community"}
    assert logs[0].json["metadata"] == {"cause": "test-cause", "role": "member"}
    assert logs[0].json["user"]["id"] == str(user.id)


def test_apply_role_change_creates_audit_log(app, communities, user, search_clear):
    member = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    curator = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:curator#perun.cesnet.cz",
        community_slug="test-community",
        role="curator",
    )

    with UnitOfWork() as uow:
        member.apply(user, "grant-member", uow)
        uow.commit()

    with UnitOfWork() as uow:
        curator.apply(user, "promote-to-curator", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="community.member_added")
    assert len(logs) == 2
    causes = {log.json["metadata"]["cause"] for log in logs}
    assert causes == {"grant-member", "promote-to-curator"}
    roles = {log.json["metadata"]["role"] for log in logs}
    assert roles == {"member", "curator"}


def test_apply_idempotent_membership_does_not_create_audit_log(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "first-apply", uow)
        uow.commit()

    with UnitOfWork() as uow:
        entitlement.apply(user, "second-apply", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="community.member_added")
    assert len(logs) == 1
    assert logs[0].json["metadata"]["cause"] == "first-apply"


def test_remove_community_membership_creates_audit_log(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "grant", uow)
        uow.commit()

    with UnitOfWork() as uow:
        entitlement.remove(user, "revoke", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="community.member_removed")
    assert len(logs) == 1
    assert logs[0].json["resource"] == {"type": "community", "id": "test-community"}
    assert logs[0].json["metadata"]["cause"] == "revoke"


def test_remove_without_existing_membership_does_not_create_audit_log(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.remove(user, "revoke", uow)
        uow.commit()

    assert _audit_logs(user.id, action="community.member_removed") == []


def test_apply_role_creates_audit_log(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "grant-admin", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="role.member_added")
    assert len(logs) == 1
    assert logs[0].resource_type == "role"
    assert logs[0].json["resource"] == {"type": "role", "id": "administration"}
    assert logs[0].json["metadata"]["cause"] == "grant-admin"


def test_remove_role_creates_audit_log(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "grant-admin", uow)
        uow.commit()

    with UnitOfWork() as uow:
        entitlement.remove(user, "revoke-admin", uow)
        uow.commit()

    logs = _audit_logs(user.id, action="role.member_removed")
    assert len(logs) == 1
    assert logs[0].json["resource"] == {"type": "role", "id": "administration"}
    assert logs[0].json["metadata"]["cause"] == "revoke-admin"


def test_remove_role_without_existing_role_does_not_create_audit_log(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.remove(user, "revoke-admin", uow)
        uow.commit()

    assert _audit_logs(user.id, action="role.member_removed") == []
