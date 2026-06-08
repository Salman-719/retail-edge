import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PunchInStation(Base):
    """The punch-in machine's camera + floor location for one config version.

    One per version (UNIQUE version_id). world_x/world_y are floor coordinates in
    metres (same coordinate system as zones / camera positions after the P1 fix).
    """

    __tablename__ = "punch_in_stations"
    __table_args__ = (UniqueConstraint("version_id", name="uq_punch_station_per_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("store_config_versions.id", ondelete="CASCADE"), nullable=False
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    camera_config_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("camera_configs.id", ondelete="CASCADE"), nullable=False
    )
    world_x: Mapped[float] = mapped_column(Float, nullable=False)
    world_y: Mapped[float] = mapped_column(Float, nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
