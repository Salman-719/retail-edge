"""IEP3-owned tables (cross-camera reconciliation)."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base


class GlobalIdentity(Base):
    """Authoritative registry of store-wide identities."""

    __tablename__ = "global_identities"

    global_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    first_seen_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    lost_since_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Last canonical floor position (updated each batch in Process 2). Lets the
    # cross-camera gate do a single-row lookup instead of scanning history (M5 §9).
    last_floor_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_floor_y: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint("state IN ('active','lost','exited')", name="state_valid"),
        Index("ix_global_identities_store_state", "store_id", "state"),
        Index("ix_global_identities_state_lost", "state", "lost_since_batch"),
    )


class GlobalLocalMapping(Base):
    """LocalID -> GlobalID linkage with full history. Old links preserved as
    is_active=False rows for audit."""

    __tablename__ = "global_local_mapping"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    global_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_identities.global_id"), nullable=False
    )
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    local_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linked_at_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    unlinked_at_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        # Only one ACTIVE LocalID per camera per GlobalID (partial unique index).
        Index(
            "uq_glm_global_camera_active",
            "global_id",
            "camera_id",
            unique=True,
            postgresql_where=(is_active == True),  # noqa: E712
        ),
        Index("ix_global_local_mapping_local_id", "local_id"),
        Index("ix_global_local_mapping_global_active", "global_id", "is_active"),
    )


class GlobalEmbedding(Base):
    """Per-camera centroid for each GlobalID. Used for cross-camera ReID."""

    __tablename__ = "global_embeddings"

    global_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_identities.global_id"), primary_key=True
    )
    camera_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at_batch: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_global_embeddings_global_id", "global_id"),)


class GlobalTrackingHistory(Base):
    """Canonical store-wide position log. One row per GlobalID per batch.
    Consumed by alerts, analytics, dashboards."""

    __tablename__ = "global_tracking_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    global_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_identities.global_id"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    floor_x: Mapped[float] = mapped_column(Float, nullable=False)
    floor_y: Mapped[float] = mapped_column(Float, nullable=False)
    zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_camera: Mapped[str] = mapped_column(String(64), nullable=False)
    source_local_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selection_score: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gth_global_ts", "global_id", "timestamp_ms"),
        Index("ix_gth_store_ts", "store_id", "timestamp_ms"),
        Index("ix_gth_batch", "batch_number"),
        Index("ix_gth_zone_ts", "zone_id", "timestamp_ms"),
    )
