import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AlertRuleZone(Base):
    __tablename__ = "alert_rule_zones"

    alert_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("alert_rules.id", ondelete="CASCADE"), primary_key=True
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="CASCADE"), primary_key=True
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    threshold_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    followup_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    people_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=True
    )
    only_during_shift: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Eager-loaded so a rule's zones are available without a second round trip.
    zones: Mapped[list["AlertRuleZone"]] = relationship(
        "AlertRuleZone", cascade="all, delete-orphan", lazy="selectin"
    )
