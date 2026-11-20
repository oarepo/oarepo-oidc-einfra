# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for the commandline tools."""

from __future__ import annotations

from invenio_accounts.proxies import current_datastore
from oarepo_runtime.cli import oarepo

from oarepo_oidc_einfra.models import EInfraUserEntitlements

MEMBER = "urn:geant:cesnet.cz:res:communities:test-community:role:member"


def _user_with_entitlements(db, email, entitlements):
    user = current_datastore.create_user(email=email, active=True)
    db.session.flush()
    db.session.add(EInfraUserEntitlements(user_id=user.id, entitlements=entitlements))
    db.session.commit()
    return user.id


def _entitlements(db, user_id):
    db.session.expire_all()
    return db.session.query(EInfraUserEntitlements).filter_by(user_id=user_id).one().entitlements


def test_update_issuers(app, db):
    """Matching entitlements get the new issuer, all others are kept untouched."""
    matching = _user_with_entitlements(
        db,
        "cli-matching@example.com",
        [f"{MEMBER}#perun.cesnet.cz", f"{MEMBER}#other.cz", "urn:no-issuer"],
    )
    non_matching = _user_with_entitlements(db, "cli-non-matching@example.com", [f"{MEMBER}#other.cz"])

    result = app.test_cli_runner().invoke(oarepo, ["update-issuers", "perun.cesnet.cz", "somethingother.cz"])
    assert result.exit_code == 0, result.output

    assert _entitlements(db, matching) == [
        f"{MEMBER}#somethingother.cz",
        f"{MEMBER}#other.cz",
        "urn:no-issuer",
    ]
    assert _entitlements(db, non_matching) == [f"{MEMBER}#other.cz"]
