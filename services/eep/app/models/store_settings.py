import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StoreSettings(Base):
    __tablename__ = "store_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), unique=True)
    activation_countdown_sec: Mapped[int] = mapped_column(Integer, default=60)
    chunk_duration_sec: Mapped[int] = mapped_column(Integer, default=300)
    chunk_overlap_sec: Mapped[int] = mapped_column(Integer, default=30)
    frame_sample_rate_fps: Mapped[int] = mapped_column(Integer, default=5)
    active_config_cache_ttl_sec: Mapped[int] = mapped_column(Integer, default=300)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
