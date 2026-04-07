"""Analytics, alert, and tracking-history ORM models (Milestone 3+)."""
import uuid
from datetime import datetime

from sqlalchemy import String, Float, JSON, ForeignKey, DateTime, Index, func
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TrackingHistory(Base):
    """Per-frame tracking records written by IEP2 (Milestone 3+)."""
    __tablename__ = "tracking_history"
    __table_args__ = (
        Index("ix_tracking_history_store_ts", "store_id", "timestamp"),
        Index("ix_tracking_history_camera", "camera_id"),
        Index("ix_tracking_history_zone", "zone_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    camera_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cameras.id", ondelete="SET NULL"))
    person_id: Mapped[str | None] = mapped_column(String(100))
    zone_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("zones.id", ondelete="SET NULL"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    floor_x: Mapped[float | None] = mapped_column(Float)
    floor_y: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_store_status", "store_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(100))  # queue|staff_absence
    status: Mapped[str] = mapped_column(String(50), default="active")  # active|resolved
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalyticsResult(Base):
    __tablename__ = "analytics_results"
    __table_args__ = (
        Index("ix_analytics_results_store_type", "store_id", "type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(100))
    time_range_start: Mapped[datetime | None] = mapped_column(DateTime)
    time_range_end: Mapped[datetime | None] = mapped_column(DateTime)
    result: Mapped[dict | None] = mapped_column(JSON)
    s3_key: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
