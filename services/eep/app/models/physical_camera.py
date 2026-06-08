import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PhysicalCamera(Base):
    __tablename__ = "physical_cameras"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cloud_stream_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stream_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_password: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mounting: Mapped[str] = mapped_column(String(20), nullable=True, default="ceiling")
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Stream resolution — auto-detected from the live RTSP stream, never user input.
    stream_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stream_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Camera intrinsics (M7-S1). lens/FOV are user-supplied; fx/fy/cx/cy and
    # dist_coeffs are computed from FOV + stream resolution.
    lens_focal_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    h_fov_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_fov_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx: Mapped[float | None] = mapped_column(Float, nullable=True)
    fy: Mapped[float | None] = mapped_column(Float, nullable=True)
    cx: Mapped[float | None] = mapped_column(Float, nullable=True)
    cy: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_coeffs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    intrinsics_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
