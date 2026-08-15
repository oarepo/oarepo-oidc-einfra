# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for CommunityEntitlement.apply() and remove()."""

from __future__ import annotations

import uuid

import pytest
from invenio_access.permissions import system_identity
from invenio_communities.members.records.api import Member
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from invenio_db.uow import UnitOfWork

from oarepo_oidc_einfra.perun.entitlements import CommunityEntitlement


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


def _membership(community_id, user_id):
    return db.session.query(MemberModel).filter_by(community_id=community_id, user_id=user_id).first()


def _search_members(community_id):
    """Search the members of a community via the members service, refreshing the index first."""
    Member.index.refresh()
    results = current_communities.service.members.search(system_identity, community_id)
    return list(results)


def test_apply_creates_membership(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "test-cause", uow)
        uow.commit()

    member = _membership(entitlement.community.id, user.id)
    assert member is not None
    assert member.role == "member"
    assert member.active is True

    hits = _search_members(entitlement.community.id)
    assert len(hits) == 1
    assert hits[0]["member"]["id"] == str(user.id)
    assert hits[0]["role"] == "member"


def test_apply_is_idempotent_for_existing_membership(app, communities, user, search_clear):
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

    members = db.session.query(MemberModel).filter_by(community_id=entitlement.community.id, user_id=user.id).all()
    assert len(members) == 1
    assert members[0].role == "member"
    assert members[0].active is True

    hits = _search_members(entitlement.community.id)
    assert len(hits) == 1
    assert hits[0]["role"] == "member"


def test_apply_updates_role_of_existing_membership(app, communities, user, search_clear):
    member_entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    curator_entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:curator#perun.cesnet.cz",
        community_slug="test-community",
        role="curator",
    )

    with UnitOfWork() as uow:
        member_entitlement.apply(user, "grant-member", uow)
        uow.commit()

    with UnitOfWork() as uow:
        curator_entitlement.apply(user, "promote-to-curator", uow)
        uow.commit()

    members = (
        db.session.query(MemberModel).filter_by(community_id=member_entitlement.community.id, user_id=user.id).all()
    )
    assert len(members) == 1
    assert members[0].role == "curator"
    assert members[0].active is True

    hits = _search_members(member_entitlement.community.id)
    assert len(hits) == 1
    assert hits[0]["role"] == "curator"


def test_apply_reactivates_inactive_membership(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "first-apply", uow)
        uow.commit()

    member = _membership(entitlement.community.id, user.id)
    member.active = False
    db.session.commit()

    with UnitOfWork() as uow:
        entitlement.apply(user, "reactivate", uow)
        uow.commit()

    member = _membership(entitlement.community.id, user.id)
    assert member.active is True

    hits = _search_members(entitlement.community.id)
    assert len(hits) == 1


def test_remove_deletes_existing_membership(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.apply(user, "test-cause", uow)
        uow.commit()
    assert _membership(entitlement.community.id, user.id) is not None
    assert len(_search_members(entitlement.community.id)) == 1

    with UnitOfWork() as uow:
        entitlement.remove(user, "test-removal", uow)
        uow.commit()

    assert _membership(entitlement.community.id, user.id) is None
    assert len(_search_members(entitlement.community.id)) == 0


def test_remove_without_existing_membership_is_noop(app, communities, user, search_clear):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )

    with UnitOfWork() as uow:
        entitlement.remove(user, "test-removal", uow)
        uow.commit()

    assert _membership(entitlement.community.id, user.id) is None
    assert len(_search_members(entitlement.community.id)) == 0
