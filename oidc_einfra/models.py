import uuid

from invenio_communities.communities.records.models import CommunityMetadata
from invenio_db import db
from invenio_records.models import Timestamp
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy_utils.types import UUIDType


class CommunityAAIMapping(db.Model, Timestamp):
    __tablename__ = "communities_aai_mapping"

    id = db.Column(UUIDType, primary_key=True, default=uuid.uuid4)

    @declared_attr
    def community_id(cls):
        """Foreign key to the related community."""
        return db.Column(
            UUIDType,
            db.ForeignKey(CommunityMetadata.id, ondelete="CASCADE"),
            nullable=False,
        )

    role = db.Column(db.String(50), nullable=False)

    aai_vo_uuid = db.Column(UUIDType, nullable=True)

    aai_group_uuid = db.Column(UUIDType, nullable=True)

    managed = db.Column(db.Boolean(), nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "community_id", "aai_vo_uuid", "aai_group_uuid", name="uix_vo_group"
        ),
        UniqueConstraint("community_id", "role", name="uix_role"),
    )
