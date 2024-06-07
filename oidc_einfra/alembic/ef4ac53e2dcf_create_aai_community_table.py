#
# This file is part of Invenio.
# Copyright (C) 2016-2018 CERN.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Create aai-community table"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "ef4ac53e2dcf"
down_revision = "cae29cd0782e"
branch_labels = ()
depends_on = None


def upgrade():
    """Upgrade database."""
    op.create_table(
        "communities_aai_mapping",
        sa.Column(
            "created",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"),
            nullable=False,
        ),
        sa.Column(
            "updated",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"),
            nullable=False,
        ),
        sa.Column("id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("aai_vo_uuid", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
        sa.Column(
            "aai_group_uuid", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True
        ),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column(
            "community_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["community_id"],
            ["communities_metadata.id"],
            name=op.f("fk_communities_aai_mapping_community_id_communities_metadata"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_communities_aai_mapping")),
        sa.UniqueConstraint("aai_vo_uuid", "aai_group_uuid", name="uix_vo_group"),
    )


def downgrade():
    """Downgrade database."""
    op.drop_table("communities_aai_mapping")
