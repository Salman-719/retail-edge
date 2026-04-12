"""Zone and Obstacle ORM models."""
import uuid
from datetime import datetime

from sqlalchemy import String, JSON, ForeignKey, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))  # entrance|checkout|aisle|staff_only|general
    points: Mapped[list] = mapped_column(JSON)  # [{x: float, y: float}, ...]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship(back_populates="zones")


class Obstacle(Base):
    __tablename__ = "obstacles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(String(36), ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    points: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="obstacles")
