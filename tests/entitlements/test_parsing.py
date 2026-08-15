# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for entitlement parsing."""

from __future__ import annotations

import pytest

from oarepo_oidc_einfra.perun.entitlements import (
    CommunityEntitlement,
    Entitlement,
    EntitlementError,
    GlobalRoleEntitlement,
)


@pytest.mark.parametrize(
    ("urn", "expected_class", "expected_kwargs"),
    [
        (
            "urn:geant:cesnet.cz:res:communities:test-community:role:member#perun.cesnet.cz",
            CommunityEntitlement,
            {"community_slug": "test-community", "role": "member"},
        ),
        (
            "urn:geant:cesnet.cz:res:communities:another-community:role:curator#perun.cesnet.cz",
            CommunityEntitlement,
            {"community_slug": "another-community", "role": "curator"},
        ),
        (
            "urn:geant:cesnet.cz:res:roles:administration#perun.cesnet.cz",
            GlobalRoleEntitlement,
            {"role": "administration"},
        ),
    ],
)
def test_successful_parsing(app, communities, roles, urn, expected_class, expected_kwargs):
    entitlement = Entitlement.from_string(urn)
    if expected_class is CommunityEntitlement:
        expected_entitlement = CommunityEntitlement.from_slug(entitlement=urn, **expected_kwargs)
    else:
        expected_entitlement = GlobalRoleEntitlement.from_role_name(entitlement=urn, **expected_kwargs)
    assert entitlement == expected_entitlement


@pytest.mark.parametrize(
    ("urn", "expected_exception", "expected_message"),
    [
        (
            "urn:unknown:cesnet.cz:res:communities:test:role:members#perun.cesnet.cz",
            EntitlementError,
            "Unknown entitlement namespace",
        ),
        (
            "urn:geant:unknown-prefix:res:communities:test:role:members#perun.cesnet.cz",
            EntitlementError,
            "Unknown entitlement prefix",
        ),
        (
            "urn:geant:cesnet.cz:res:unknown:type:stuff#perun.cesnet.cz",
            EntitlementError,
            "Unknown entitlement type",
        ),
        (
            "urn:geant:cesnet.cz:#perun.cesnet.cz",
            EntitlementError,
            "Unknown entitlement type",
        ),
        (
            "urn:geant:cesnet.cz:res:communities:another-community:role:bad#perun.cesnet.cz",
            EntitlementError,
            "Unknown community role",
        ),
        (
            "not-a-urn-at-all",
            EntitlementError,
            "Malformed entitlement URN",
        ),
    ],
)
def test_unsuccessful_parsing(app, communities, urn, expected_exception, expected_message):
    """Test that unknown/malformed entitlement URNs raise EntitlementException, and nothing else."""
    with pytest.raises(expected_exception, match=expected_message):
        Entitlement.from_string(urn)
