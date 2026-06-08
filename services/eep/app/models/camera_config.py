import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CameraConfig(Base):
    __tablename__ = "camera_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("store_config_versions.id", ondelete="CASCADE"), nullable=False
    )
    physical_camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("physical_cameras.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    position_x: Mapped[float] = mapped_column(Float, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, nullable=False)
    height_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    viewing_angle_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fov_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    frame_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frame_source: Mapped[str] = mapped_column(String(20), nullable=True, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    video_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_quality_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
