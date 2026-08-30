# SPDX-FileCopyrightText: 2016-2018 CERN.
# SPDX-License-Identifier: MIT

"""data-fix-requests"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1788078205'
down_revision = '1786795059'
branch_labels = ()
depends_on = None

REMOVED_REQUEST_TYPES = ("aai-community-invitation",)
"""Request types that no longer exist in the code but might already have
created request_metadata rows (and associated community memberships)."""


def upgrade():
    """Remove requests of types that were removed from the code base.

    Community memberships/invitations that reference such a request are
    fixed up first: active ones just lose the (now dangling) request
    reference, inactive ones (pending/declined/cancelled invitations) are
    removed altogether, as they have no meaning without the request that
    created them.
    """
    bind = op.get_bind()

    json_type = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")

    request_metadata = sa.table(
        "request_metadata",
        sa.column("id", sqlalchemy_utils.UUIDType),
        sa.column("json", json_type),
    )
    communities_members = sa.table(
        "communities_members",
        sa.column("id", sqlalchemy_utils.UUIDType),
        sa.column("request_id", sqlalchemy_utils.UUIDType),
        sa.column("active", sa.Boolean),
    )
    communities_archivedinvitations = sa.table(
        "communities_archivedinvitations",
        sa.column("id", sqlalchemy_utils.UUIDType),
        sa.column("request_id", sqlalchemy_utils.UUIDType),
        sa.column("active", sa.Boolean),
    )

    request_ids = [
        row.id
        for row in bind.execute(sa.select(request_metadata.c.id, request_metadata.c.json))
        if row.json and row.json.get("type") in REMOVED_REQUEST_TYPES
    ]

    if not request_ids:
        return

    for members_table in (communities_members, communities_archivedinvitations):
        bind.execute(
            sa.delete(members_table).where(
                members_table.c.request_id.in_(request_ids),
                members_table.c.active.is_(False),
            )
        )
        bind.execute(
            sa.update(members_table)
            .where(
                members_table.c.request_id.in_(request_ids),
                members_table.c.active.is_(True),
            )
            .values(request_id=None)
        )

    bind.execute(sa.delete(request_metadata).where(request_metadata.c.id.in_(request_ids)))


def downgrade():
    """Downgrade database."""
    # data migration - not reversible
    pass
