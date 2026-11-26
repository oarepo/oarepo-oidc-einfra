# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Commandline tools for oidc einfra integration."""

from __future__ import annotations

import click
from flask.cli import with_appcontext
from invenio_db import db
from oarepo_runtime.cli import oarepo


@oarepo.command(name="update-issuers")
@click.argument("old_issuer")
@click.argument("new_issuer")
@with_appcontext
def update_issuers(old_issuer: str, new_issuer: str) -> None:
    """Update all issuers in e-infra capabilities."""
    from oarepo_oidc_einfra.models import EInfraUserEntitlements

    old_issuer = f"#{old_issuer}"
    new_issuer = f"#{new_issuer}"
    for user_entitlement in db.session.query(EInfraUserEntitlements).all():
        new_entitlements = [
            x.removesuffix(old_issuer) + new_issuer if x.endswith(old_issuer) else x
            for x in user_entitlement.entitlements
        ]
        if new_entitlements != user_entitlement.entitlements:
            user_entitlement.entitlements = new_entitlements
    db.session.commit()
