# SPDX-FileCopyrightText: 2026 CESNET z.s.p.o.
# SPDX-License-Identifier: MIT
"""User capabilities model."""

from __future__ import annotations

from invenio_accounts.models import User
from invenio_db import db
from sqlalchemy.dialects import postgresql
from sqlalchemy_utils.types import JSONType

JSON = (
    db.JSON()
    .with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
    .with_variant(JSONType(), "sqlite")
    .with_variant(JSONType(), "mysql")
)


class EInfraUserEntitlements(db.Model):
    """Stores user capabilities from the Perun service as it was observed during the last login."""

    __tablename__ = "einfra_user_entitlements"

    user_id = db.Column(
        db.Integer(),
        db.ForeignKey(User.id, ondelete="CASCADE"),
        primary_key=True,
    )
    """Foreign key to the user, also serving as the primary key (one row per user)."""

    user = db.relationship(
        "User", backref=db.backref("einfra_perun_capabilities", uselist=False, cascade="all, delete-orphan")
    )
    """Relationship to the user."""

    entitlements = db.Column(
        JSON,
        nullable=False,
        default=list,
    )
    """The user's entitlements as a list of strings."""
