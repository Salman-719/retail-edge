import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PunchEvent(Base):
    """An ingested punch-in record, resolved by the EEP punch_resolver.

    punched_at_ms is epoch milliseconds (aligns with
    global_tracking_history.timestamp_ms). status lifecycle:
    pending -> linked | unmatched | expired.
    """

    __tablename__ = "punch_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    punched_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="device")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # DB-level FK to global_identities(global_id) is enforced by schema.sql / migration
    # 0013. No ORM ForeignKey here: global_identities is not an ORM-mapped table in EEP
    # (IEP3 owns it via raw SQL), so a declared FK would dangle in metadata.create_all.
    linked_global_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    match_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
