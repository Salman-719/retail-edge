import uuid
from datetime import datetime, time, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    Time,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StoreOperatingHours(Base):
    """Per-weekday open/close for a store — the master clock (C2).

    One row per (store, day_of_week). day_of_week uses Python weekday():
    0 = Monday … 6 = Sunday. Overnight windows (close <= open) wrap past
    midnight. open_time/close_time are nullable; they are required (and must
    differ) only when is_open — enforced in the app, not the DB. Replaces the
    retired per-camera camera_schedules.
    """

    __tablename__ = "store_operating_hours"
    __table_args__ = (
        CheckConstraint(
            "day_of_week >= 0 AND day_of_week <= 6",
            name="store_operating_hours_day_of_week_check",
        ),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    open_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    close_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
