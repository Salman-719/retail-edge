import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShiftInstance(Base):
    __tablename__ = "shift_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sections.id", ondelete="CASCADE"), nullable=False
    )
    shift_pattern_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shift_patterns.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    break_duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # scheduled | active | completed | absent | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ShiftAssignment(Base):
    __tablename__ = "shift_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    shift_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shift_instances.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    attendance_status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class BreakRecord(Base):
    __tablename__ = "break_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shift_assignments.id", ondelete="CASCADE"), nullable=False
    )
    break_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    break_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    break_type: Mapped[str] = mapped_column(String(20), nullable=False, default="taken")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
