# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for entitlement core, sort_key and deduplicate_by_core."""

from __future__ import annotations

import pytest

from oarepo_oidc_einfra.perun.entitlements import (
    CommunityEntitlement,
    Entitlement,
    GlobalRoleEntitlement,
)


@pytest.fixture(scope="module")
def global_roles(app, database):
    """Create global roles used by sorting/dedup tests."""
    from invenio_accounts.proxies import current_datastore

    roles = [
        current_datastore.create_role(name="administration"),
        current_datastore.create_role(name="trusted-user"),
    ]
    current_datastore.commit()

    return roles


def test_base_entitlement_core_and_sort_key(app):
    entitlement = Entitlement(entitlement="urn:geant:cesnet.cz:res:something#perun.cesnet.cz")
    assert entitlement.core == ()
    assert entitlement.sort_key == 0


def test_global_role_entitlement_core_and_sort_key(app, global_roles):
    entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )
    assert entitlement.core == ("role", "administration")
    assert entitlement.sort_key == -1


def test_community_entitlement_core(app, communities):
    entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    assert entitlement.core == ("community", "test-community")


@pytest.mark.parametrize(("role", "expected_sort_key"), [("curator", 2), ("member", 1)])
def test_community_entitlement_sort_key(app, communities, role, expected_sort_key):
    entitlement = CommunityEntitlement.from_slug(
        entitlement=f"urn:geant:cesnet.cz:res:communities:test-community:role:{role}#perun.cesnet.cz",
        community_slug="test-community",
        role=role,
    )
    assert entitlement.sort_key == expected_sort_key


def test_community_sort_key_ranks_curator_above_member(app, communities):
    curator = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:curator#perun.cesnet.cz",
        community_slug="test-community",
        role="curator",
    )
    member = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    assert curator.sort_key > member.sort_key


def test_global_role_sorts_below_community_roles(app, communities, global_roles):
    global_entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )
    member = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    assert global_entitlement.sort_key < member.sort_key


def test_deduplicate_by_core_keeps_highest_sort_key_for_same_community(app, communities):
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

    result = Entitlement.deduplicate_by_core([member, curator])

    assert result == [curator]


def test_deduplicate_by_core_keeps_entitlements_with_different_cores(app, communities, global_roles):
    community_entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
        community_slug="test-community",
        role="member",
    )
    another_community_entitlement = CommunityEntitlement.from_slug(
        entitlement="urn:geant:cesnet.cz:res:communities:another-community:role:curator#perun.cesnet.cz",
        community_slug="another-community",
        role="curator",
    )
    global_entitlement = GlobalRoleEntitlement.from_role_name(
        entitlement="urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
        role="administration",
    )

    result = Entitlement.deduplicate_by_core([community_entitlement, another_community_entitlement, global_entitlement])

    assert set(result) == {community_entitlement, another_community_entitlement, global_entitlement}


def test_deduplicate_by_core_empty_list(app):
    assert Entitlement.deduplicate_by_core([]) == []
