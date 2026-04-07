"""Store and FloorPlan ORM models."""
import uuid
from datetime import datetime

from sqlalchemy import String, Float, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


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


class FloorPlan(Base):
    __tablename__ = "floor_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    s3_key: Mapped[str | None] = mapped_column(String(1000))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
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
