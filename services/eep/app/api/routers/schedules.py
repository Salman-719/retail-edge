"""Camera schedule CRUD endpoints."""
import logging
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core import orchestrator
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.camera_config import CameraConfig
from app.models.camera_schedule import CameraSchedule
from app.models.version import StoreConfigVersion
from app.schemas.camera_schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate, TriggerRequest
from app.tasks.camera_scheduler import mark_running, mark_stopped

log = logging.getLogger(__name__)

router = APIRouter(tags=["schedules"])


async def _get_schedule_or_404(
    schedule_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession
) -> CameraSchedule:
    result = await db.execute(
        select(CameraSchedule).where(
            CameraSchedule.id == schedule_id,
            CameraSchedule.store_id == store_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Schedule not found", "code": "NOT_FOUND"})
    return row


async def _validate_camera_config_belongs_to_store(
    camera_config_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession
) -> None:
    result = await db.execute(
        select(CameraConfig.id)
        .join(StoreConfigVersion, StoreConfigVersion.id == CameraConfig.version_id)
        .where(
            CameraConfig.id == camera_config_id,
            StoreConfigVersion.store_id == store_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Camera config not found for this store", "code": "NOT_FOUND"},
        )


@router.get("/store/{slug}/schedules", response_model=List[ScheduleResponse])
async def list_schedules(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CameraSchedule).where(CameraSchedule.store_id == ctx.store_id)
    )
    return result.scalars().all()


@router.post("/store/{slug}/schedules", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _validate_camera_config_belongs_to_store(body.camera_config_id, ctx.store_id, db)

    schedule = CameraSchedule(
        store_id=ctx.store_id,
        camera_config_id=body.camera_config_id,
        days_of_week=body.days_of_week,
        start_time=body.start_time,
        end_time=body.end_time,
        is_active=body.is_active,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return schedule


@router.patch("/store/{slug}/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    schedule = await _get_schedule_or_404(schedule_id, ctx.store_id, db)

    changed = False
    for field in body.model_fields:
        val = getattr(body, field)
        if val is not None:
            setattr(schedule, field, val)
            changed = True

    if changed:
        schedule.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(schedule)

    return schedule


@router.delete("/store/{slug}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    schedule = await _get_schedule_or_404(schedule_id, ctx.store_id, db)
    await db.delete(schedule)
    await db.commit()


@router.post("/store/{slug}/schedules/{schedule_id}/trigger", status_code=202)
async def trigger_schedule(
    schedule_id: uuid.UUID,
    body: TriggerRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    schedule = await _get_schedule_or_404(schedule_id, ctx.store_id, db)

    store_id_str  = str(ctx.store_id)
    config_id_str = str(schedule.camera_config_id)

    try:
        if body.action == "start":
            await orchestrator.start_camera_workers(
                store_id=store_id_str,
                camera_config_id=config_id_str,
            )
            mark_running(store_id_str, config_id_str)

        elif body.action == "stop":
            await orchestrator.stop_camera_workers(
                store_id=store_id_str,
                camera_config_id=config_id_str,
            )
            mark_stopped(store_id_str, config_id_str)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Orchestration failed: {str(exc)}")

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "action": body.action,
            "schedule_id": str(schedule_id),
            "camera_config_id": config_id_str,
        },
    )
