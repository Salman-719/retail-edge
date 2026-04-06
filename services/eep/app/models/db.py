"""SQLAlchemy ORM models — full schema for RetailVision."""
import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, JSON, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ─── Store ────────────────────────────────────────────────────────────────────

class Store(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    floor_plan: Mapped["FloorPlan"] = relationship(
        back_populates="store", uselist=False, cascade="all, delete-orphan"
    )
    zones: Mapped[list["Zone"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    obstacles: Mapped[list["Obstacle"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    cameras: Mapped[list["Camera"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    employees: Mapped[list["Employee"]] = relationship(back_populates="store", cascade="all, delete-orphan")


# ─── Floor Plan ───────────────────────────────────────────────────────────────

class FloorPlan(Base):
    __tablename__ = "floor_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"))
    s3_key: Mapped[str | None] = mapped_column(String(1000))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    # Scale configuration
    origin_x: Mapped[float | None] = mapped_column(Float)
    origin_y: Mapped[float | None] = mapped_column(Float)
    scale_point1_x: Mapped[float | None] = mapped_column(Float)
    scale_point1_y: Mapped[float | None] = mapped_column(Float)
    scale_point2_x: Mapped[float | None] = mapped_column(Float)
    scale_point2_y: Mapped[float | None] = mapped_column(Float)
    real_world_distance_m: Mapped[float | None] = mapped_column(Float)
    pixels_per_meter: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship(back_populates="floor_plan")


# ─── Zones / Obstacles ────────────────────────────────────────────────────────

class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))  # entrance|checkout|aisle|staff_only|general
    points: Mapped[list] = mapped_column(JSON)  # [{x: float, y: float}, ...]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="zones")


class Obstacle(Base):
    __tablename__ = "obstacles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(255))
    points: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="obstacles")


# ─── Camera / Calibration ─────────────────────────────────────────────────────

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"))
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
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"))
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
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id", ondelete="CASCADE"))
    trajectory_data: Mapped[dict | None] = mapped_column(JSON)
    zone_occupancy: Mapped[dict | None] = mapped_column(JSON)
    heatmap_s3_key: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    camera: Mapped["Camera"] = relationship(back_populates="tracking_results")


# ─── Employees / Shifts ───────────────────────────────────────────────────────

class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(100))
    gallery_embeddings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="employees")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id", ondelete="CASCADE"))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    employee: Mapped["Employee"] = relationship(back_populates="shifts")


# ─── Analytics / Operational ──────────────────────────────────────────────────

class TrackingHistory(Base):
    """Per-frame tracking records written by IEP2 (Milestone 3+)."""
    __tablename__ = "tracking_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id"))
    camera_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cameras.id"))
    person_id: Mapped[str | None] = mapped_column(String(100))
    zone_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("zones.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    floor_x: Mapped[float | None] = mapped_column(Float)
    floor_y: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id"))
    type: Mapped[str] = mapped_column(String(100))  # queue|staff_absence
    status: Mapped[str] = mapped_column(String(50), default="active")  # active|resolved
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalyticsResult(Base):
    __tablename__ = "analytics_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id"))
    type: Mapped[str] = mapped_column(String(100))
    time_range_start: Mapped[datetime | None] = mapped_column(DateTime)
    time_range_end: Mapped[datetime | None] = mapped_column(DateTime)
    result: Mapped[dict | None] = mapped_column(JSON)
    s3_key: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
