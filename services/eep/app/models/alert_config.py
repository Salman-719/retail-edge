import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), unique=True)
    shift_start_grace_min: Mapped[int] = mapped_column(Integer, default=15)
    absence_threshold_min: Mapped[int] = mapped_column(Integer, default=15)
    queue_people_threshold: Mapped[int] = mapped_column(Integer, default=10)
    queue_wait_min_threshold: Mapped[int] = mapped_column(Integer, default=7)
    queue_alert_cooldown_min: Mapped[int] = mapped_column(Integer, default=15)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
