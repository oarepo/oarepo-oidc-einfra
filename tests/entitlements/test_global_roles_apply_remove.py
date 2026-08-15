# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for GlobalRoleEntitlement.apply() and remove()."""

from __future__ import annotations

import uuid

import pytest
from invenio_db.uow import UnitOfWork

from oarepo_oidc_einfra.perun.entitlements import GlobalRoleEntitlement


@pytest.fixture
def user(app, database):
    """Create a fresh user for apply/remove tests."""
    from invenio_accounts.proxies import current_datastore

    new_user = current_datastore.create_user(
        email=f"{uuid.uuid4().hex}@example.org",
        password="not-used",  # noqa S106
        active=True,
    )
    current_datastore.commit()

    return new_user


def test_apply_adds_role(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "test-cause", uow)
        uow.commit()

    assert entitlement.role in user.roles


def test_apply_is_idempotent_for_existing_role(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "first-apply", uow)
        uow.commit()

    with UnitOfWork() as uow:
        entitlement.apply(user, "second-apply", uow)
        uow.commit()

    assert user.roles.count(entitlement.role) == 1


def test_remove_removes_existing_role(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "test-cause", uow)
        uow.commit()
    assert entitlement.role in user.roles

    with UnitOfWork() as uow:
        entitlement.remove(user, "test-removal", uow)
        uow.commit()

    assert entitlement.role not in user.roles


def test_remove_without_existing_role_is_noop(app, roles, user):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    with UnitOfWork() as uow:
        entitlement.remove(user, "test-removal", uow)
        uow.commit()

    assert entitlement.role not in user.roles
