"""Store operating-hours endpoints (C2) — the master clock for cameras + IEP5.

Store-level, NOT versioned through draft→publish: edited live via PUT. Cameras
inherit these hours (see app/tasks/camera_scheduler.py). Weekday 0=Mon..6=Sun.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.middleware.store_auth import (
    StoreContext,
    get_store_context,
    require_owner_or_manager,
)
from app.models.store_operating_hours import StoreOperatingHours
from app.schemas.operating_hours import (
    OperatingHourDay,
    OperatingHoursResponse,
    OperatingHoursUpdate,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["operating-hours"])


async def _load_hours(store_id, db: AsyncSession) -> OperatingHoursResponse:
    result = await db.execute(
        select(StoreOperatingHours).where(StoreOperatingHours.store_id == store_id)
    )
    by_day = {r.day_of_week: r for r in result.scalars().all()}
    days = []
    for d in range(7):
        r = by_day.get(d)
        if r is None:
            days.append(OperatingHourDay(day_of_week=d, is_open=False))
        else:
            days.append(
                OperatingHourDay(
                    day_of_week=d,
                    is_open=r.is_open,
                    open_time=r.open_time,
                    close_time=r.close_time,
                )
            )
    return OperatingHoursResponse(days=days)


@router.get("/store/{slug}/operating-hours", response_model=OperatingHoursResponse)
async def get_operating_hours(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    return await _load_hours(ctx.store_id, db)


@router.put("/store/{slug}/operating-hours", response_model=OperatingHoursResponse)
async def put_operating_hours(
    body: OperatingHoursUpdate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    now = datetime.now(timezone.utc)

    existing = await db.execute(
        select(StoreOperatingHours).where(StoreOperatingHours.store_id == ctx.store_id)
    )
    by_day = {r.day_of_week: r for r in existing.scalars().all()}

    for day in body.days:
        open_t = day.open_time if day.is_open else None
        close_t = day.close_time if day.is_open else None
        row = by_day.get(day.day_of_week)
        if row is None:
            db.add(
                StoreOperatingHours(
                    store_id=ctx.store_id,
                    day_of_week=day.day_of_week,
                    is_open=day.is_open,
                    open_time=open_t,
                    close_time=close_t,
                    updated_at=now,
                )
            )
        else:
            row.is_open = day.is_open
            row.open_time = open_t
            row.close_time = close_t
            row.updated_at = now

    await write_audit_log(
        db,
        "operating_hours_updated",
        store_id=ctx.store_id,
        user_id=ctx.user_id,
        entity_type="store",
        entity_id=ctx.store_id,
    )
    await db.commit()
    return await _load_hours(ctx.store_id, db)
