"""Shared punch-in ingestion helpers (employee-linking, S3).

Used by the production webhook (api/routers/punch.py) and the DEBUG dev trigger
(api/routers/dev_pipeline.py). The punch_events row is the durable record; the
EEP punch_resolver (S4) turns 'pending' rows into global_id links.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.punch_event import PunchEvent

# Reject punches dated meaningfully in the future (clock skew tolerance).
FUTURE_SKEW_MS = 5_000


def to_epoch_ms(dt: datetime | None) -> int:
    """Datetime -> epoch milliseconds. None = now. Naive datetimes assumed UTC."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


async def create_punch_event(
    db: AsyncSession,
    *,
    store_id: uuid.UUID,
    employee_id: uuid.UUID,
    punched_at_ms: int,
    source: str,
) -> PunchEvent:
    """Insert a pending punch_events row and return it."""
    ev = PunchEvent(
        store_id=store_id,
        employee_id=employee_id,
        punched_at_ms=punched_at_ms,
        source=source,
        status="pending",
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev
