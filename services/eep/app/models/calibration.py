import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Calibration(Base):
    __tablename__ = "calibrations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    camera_config_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("camera_configs.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Method 1: Homography
    correspondences: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    homography_matrix: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rms_reprojection_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_reprojection_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    point_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition_number: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Method 2: Calibration Files
    intrinsic_file_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extrinsic_file_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    intrinsic_matrix: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dist_coeffs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rotation_vector: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rotation_matrix: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    translation_vector: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    camera_world_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    camera_world_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    camera_world_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Verification
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Audit
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    computation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
