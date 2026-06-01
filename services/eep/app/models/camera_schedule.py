import uuid
from datetime import datetime, time, timezone
from typing import List

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Time, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CameraSchedule(Base):
    __tablename__ = "camera_schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    camera_config_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("camera_configs.id", ondelete="CASCADE"), nullable=False
    )
    days_of_week: Mapped[List[int]] = mapped_column(ARRAY(Integer), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
