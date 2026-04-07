"""Camera, Calibration, and TrackingResult ORM models."""
import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, JSON, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    position_x: Mapped[float | None] = mapped_column(Float)
    position_y: Mapped[float | None] = mapped_column(Float)
    height_meters: Mapped[float | None] = mapped_column(Float)
    rtsp_url: Mapped[str | None] = mapped_column(String(1000))
    video_s3_key: Mapped[str | None] = mapped_column(String(1000))
    video_duration: Mapped[float | None] = mapped_column(Float)
    video_fps: Mapped[float | None] = mapped_column(Float)
    video_width: Mapped[int | None] = mapped_column(Integer)
    video_height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship(back_populates="cameras")
    calibration: Mapped["Calibration"] = relationship(
        back_populates="camera", uselist=False, cascade="all, delete-orphan"
    )
    tracking_results: Mapped[list["TrackingResult"]] = relationship(
        back_populates="camera", cascade="all, delete-orphan"
    )


class Calibration(Base):
    __tablename__ = "calibrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    correspondences: Mapped[list | None] = mapped_column(JSON)
    homography_matrix: Mapped[list | None] = mapped_column(JSON)
    reprojection_error: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(50))  # ok|rejected|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    camera: Mapped["Camera"] = relationship(back_populates="calibration")


class TrackingResult(Base):
    __tablename__ = "tracking_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    trajectory_data: Mapped[dict | None] = mapped_column(JSON)
    zone_occupancy: Mapped[dict | None] = mapped_column(JSON)
    heatmap_s3_key: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    camera: Mapped["Camera"] = relationship(back_populates="tracking_results")
