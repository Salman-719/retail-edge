import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FloorPlan(Base):
    __tablename__ = "floor_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("store_config_versions.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    onboarding_method: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    original_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixels_per_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_x_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_x_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_y_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_y_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary_polygon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    image_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scale_defined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coordinate_frame_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("coordinate_frames.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
