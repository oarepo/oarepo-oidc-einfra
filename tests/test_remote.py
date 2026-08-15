# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for get_entitlements_from_userinfo_token()."""

from __future__ import annotations

import logging

import pytest
from invenio_communities.members.records.models import CommunityMetadata

from oarepo_oidc_einfra.perun.entitlements import CommunityEntitlement
from oarepo_oidc_einfra.remote import get_entitlements_from_userinfo_token

GROUP_PREFIX = "urn:geant:cesnet.cz:group:"
RES_PREFIX = "urn:geant:cesnet.cz:res:"
CESNET_SUFFIX = "#perun.cesnet.cz"

# shape of a real userinfo token from e-infra AAI, with all personally identifiable
# information replaced by made-up values and all non-"res" entitlements (group
# entitlements, which we do not handle, and unrelated URNs/URLs) genericized
USERINFO_TOKEN = {
    "sub": "9f3a7c2e1b6d4f80a5c3e9b7d2f4a6c8e0b1d3f5@einfra.cesnet.cz",
    "name": "Alex Testperson",
    "preferred_username": "testperson01",
    "given_name": "Alex",
    "family_name": "Testperson",
    "zoneinfo": "Europe/Prague",
    "locale": "cs",
    "email": "testperson01@example.org",
    "email_verified": True,
    "organization": "Example Research Organization",
    "eduperson_entitlement": [
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20ben8:Role%20member%20of%20ben8" + CESNET_SUFFIX,
        RES_PREFIX + "testing_nrp_devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:4eqq:role:member" + CESNET_SUFFIX,
        "https://example.org/ns/user-eligible-v1",
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%204eqq:Role%20member%20of%204eqq" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20uxbx:Role%20member%20of%20uxbx" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20uxbx" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200w0h:Role%20member%20of%200w0h" + CESNET_SUFFIX,
        RES_PREFIX + "communities:efbe:role:member" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20ben8" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test-nrp-devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0w0h:role:member" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0w0h" + CESNET_SUFFIX,
        "urn:mace:example.org:tcs:personal-user",
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d:Role%20member%20of%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200w0h" + CESNET_SUFFIX,
        RES_PREFIX + "communities:ben8:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%204eqq" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d:role:submitter" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20efbe:Role%20member%20of%20efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:ben8" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d:"
        "Role%20submitter%20of%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "example.org:RPs-test-services:nrp-devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:uxbx:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d" + CESNET_SUFFIX,
        RES_PREFIX + "communities:4eqq" + CESNET_SUFFIX,
        RES_PREFIX + "communities:efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:uxbx" + CESNET_SUFFIX,
    ],
}


@pytest.fixture
def known_communities(app, db):
    """Create the subset of communities from USERINFO_TOKEN that are known locally."""
    communities = [CommunityMetadata(slug=slug) for slug in ("efbe", "0d9d")]
    for community in communities:
        db.session.add(community)
    db.session.flush()

    return communities


def test_get_entitlements_from_userinfo_token_only_returns_known_community_roles(app, known_communities):
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert entitlements == {
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:efbe:role:member" + CESNET_SUFFIX,
            community_slug="efbe",
            role="member",
        ),
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:0d9d:role:member" + CESNET_SUFFIX,
            community_slug="0d9d",
            role="member",
        ),
    }


def test_get_entitlements_from_userinfo_token_ignores_unknown_communities(app):
    # none of the communities in USERINFO_TOKEN exist locally in this test
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert entitlements == set()


def test_get_entitlements_from_userinfo_token_ignores_unknown_roles(app, known_communities):
    # "0d9d:role:submitter" is present in the token, but "submitter" is not a role
    # configured in COMMUNITIES_ROLES, so it must be silently ignored
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert all(e.role != "submitter" for e in entitlements if isinstance(e, CommunityEntitlement))


def test_get_entitlements_from_userinfo_token_with_no_entitlement_claim(app):
    assert get_entitlements_from_userinfo_token({}) == set()


def test_get_entitlements_from_userinfo_token_logs_by_exception_type(app, known_communities, caplog):
    with caplog.at_level(logging.DEBUG, logger="oarepo_oidc_einfra.perun.remote"):
        get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]

    # group entitlements and "res:testing_nrp_devel" have a type we do not recognize at
    # all - routine and expected for every user, so logged at debug
    assert any("testing_nrp_devel" in m for m in debug_messages)
    assert any("group" in m for m in debug_messages)

    # these look like entitlements we should understand (or almost do), but could not
    # be resolved - a malformed URL, a foreign namespace, an unknown community and an
    # unknown role - worth an info-level note
    assert any("user-eligible" in m for m in info_messages)
    assert any("personal-user" in m for m in info_messages)
    assert any("4eqq" in m for m in info_messages)
    assert any("submitter" in m for m in info_messages)

    assert not any("testing_nrp_devel" in m for m in info_messages)
    assert not any("Unknown community: 4eqq" in m for m in debug_messages)
