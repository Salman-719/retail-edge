import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CameraRuntimeSession(Base):
    __tablename__ = "camera_runtime_sessions"

    __table_args__ = (
        CheckConstraint(
            "stop_reason IN ('schedule', 'manual', 'version_activation', 'crash', 'unknown')",
            name="crs_stop_reason_check",
        ),
        Index(
            "idx_crs_store_open",
            "store_id",
            postgresql_where=text("stopped_at IS NULL"),
        ),
        Index("idx_crs_camera_history", "physical_camera_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: ON DELETE SET NULL preserves history when hardware/config is removed.
    physical_camera_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("physical_cameras.id", ondelete="SET NULL"), nullable=True
    )
    camera_config_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("camera_configs.id", ondelete="SET NULL"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("store_config_versions.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
