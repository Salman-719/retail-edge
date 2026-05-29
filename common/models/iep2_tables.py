"""IEP2-owned tables. IEP2 writes them; IEP3 reads ``tracking_history`` and
``local_centroids`` (read-only)."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base


class TrackingHistory(Base):
    """Per-camera floor positions. One row per confirmed position update.
    Written by IEP2 (2s buffered). Read by IEP3 each batch."""

    __tablename__ = "tracking_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    local_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    floor_x: Mapped[float] = mapped_column(Float, nullable=False)
    floor_y: Mapped[float] = mapped_column(Float, nullable=False)
    zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bbox_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_area: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_tracking_history_local_id_ts", "local_id", "timestamp_ms"),
        Index("ix_tracking_history_ts", "timestamp_ms"),
        Index("ix_tracking_history_camera_ts", "camera_id", "timestamp_ms"),
    )


class LocalEmbedding(Base):
    """Persistent per-LocalID embedding store. Used for crash recovery and audit.
    IEP3 does NOT read this -- it reads local_centroids instead."""

    __tablename__ = "local_embeddings"

    local_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    captured_ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32[D] tobytes()
    yolo_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_init: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        Index("ix_local_embeddings_local_id", "local_id"),
        Index("ix_local_embeddings_camera_ts", "camera_id", "captured_ts"),
    )


class LocalCentroid(Base):
    """Current centroid per LocalID. Primary ReID interface for IEP3.
    One row per LocalID, UPSERTed on every gallery change."""

    __tablename__ = "local_centroids"

    local_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32[D] tobytes()
    updated_at_batch: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_local_centroids_camera_id", "camera_id"),)
