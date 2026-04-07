"""Employee and Shift ORM models."""
import uuid
from datetime import datetime

from sqlalchemy import String, JSON, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(100))
    gallery_embeddings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="employees")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # nullable: shift may be ongoing
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    employee: Mapped["Employee"] = relationship(back_populates="shifts")
