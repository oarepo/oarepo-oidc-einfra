# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Entitlement apply/remove must still work when AUDIT_LOGS_ENABLED is off (the library default)."""

from __future__ import annotations

import uuid

import pytest
from invenio_audit_logs.records.api import AuditLog
from invenio_communities.members.records.models import MemberModel
from invenio_db import db
from invenio_db.uow import UnitOfWork

from oarepo_oidc_einfra.perun.entitlements import CommunityEntitlement, GlobalRoleEntitlement


@pytest.fixture(scope="module")
def app_config(app_config):
    """Override the parent app_config to restore the AUDIT_LOGS_ENABLED library default (off)."""
    app_config["AUDIT_LOGS_ENABLED"] = False
    return app_config


@pytest.fixture
def user(app, database):
    """Create a fresh user for the test."""
    from invenio_accounts.proxies import current_datastore

    new_user = current_datastore.create_user(
        email=f"{uuid.uuid4().hex}@example.org",
        password="not-used",  # noqa: S106
        active=True,
    )
    current_datastore.commit()

    return new_user


def test_apply_and_remove_do_not_fail_when_audit_logs_disabled(app, communities, roles, user, search_clear):
    community_entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    role_entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        community_entitlement.apply(user, "test-cause", uow)
        role_entitlement.apply(user, "test-cause", uow)
        uow.commit()

    membership = (
        db.session.query(MemberModel)
        .filter_by(community_id=community_entitlement.community.id, user_id=user.id)
        .first()
    )
    assert membership is not None
    assert role_entitlement.role in user.roles
    assert db.session.query(AuditLog.model_cls).filter_by(user_id=str(user.id)).count() == 0

    with UnitOfWork() as uow:
        community_entitlement.remove(user, "test-cause", uow)
        role_entitlement.remove(user, "test-cause", uow)
        uow.commit()

    membership = (
        db.session.query(MemberModel)
        .filter_by(community_id=community_entitlement.community.id, user_id=user.id)
        .first()
    )
    assert membership is None
    assert role_entitlement.role not in user.roles
    assert db.session.query(AuditLog.model_cls).filter_by(user_id=str(user.id)).count() == 0
