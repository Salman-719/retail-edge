import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CoordinateFrame(Base):
    __tablename__ = "coordinate_frames"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("store_config_versions.id", ondelete="CASCADE"), nullable=False
    )
    origin_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    x_axis_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    units: Mapped[str] = mapped_column(String(20), nullable=False, default="meters")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
