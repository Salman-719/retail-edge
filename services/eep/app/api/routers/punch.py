"""Punch-in ingestion endpoints (employee-linking, S3).

Production-shaped webhook a real punch machine calls. Persists a pending
punch_events row; the EEP punch_resolver (S4) links it to a global_id.

Auth (MVP): store owner/manager via get_store_context. A real device would
authenticate with a per-store device token — left as a follow-up; the punch
machine integration point is the route shape, which is stable.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.punch_ingest import FUTURE_SKEW_MS, create_punch_event, now_ms, to_epoch_ms
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.employee import Employee
from app.models.punch_event import PunchEvent
from app.schemas.punch import PunchEventRequest, PunchEventResponse

router = APIRouter(tags=["punch"])


async def _resolve_employee(
    db: AsyncSession,
    store_id: uuid.UUID,
    employee_id: uuid.UUID | None,
    employee_code: str | None,
) -> Employee:
    query = select(Employee).where(
        Employee.store_id == store_id,
        Employee.is_active == True,  # noqa: E712
    )
    if employee_id is not None:
        query = query.where(Employee.id == employee_id)
    else:
        query = query.where(Employee.employee_code == employee_code)
    emp = (await db.execute(query)).scalar_one_or_none()
    if emp is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Employee not found or inactive", "code": "EMPLOYEE_NOT_FOUND"},
        )
    return emp


@router.post("/store/{slug}/punch-events", response_model=PunchEventResponse, status_code=201)
async def record_punch_event(
    slug: str,
    body: PunchEventRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    emp = await _resolve_employee(db, ctx.store_id, body.employee_id, body.employee_code)
    punched_at_ms = to_epoch_ms(body.punched_at)
    if punched_at_ms > now_ms() + FUTURE_SKEW_MS:
        raise HTTPException(
            status_code=422,
            detail={"error": "punched_at is in the future", "code": "PUNCH_IN_FUTURE"},
        )

    ev = await create_punch_event(
        db,
        store_id=ctx.store_id,
        employee_id=emp.id,
        punched_at_ms=punched_at_ms,
        source="device",
    )
    return ev


@router.get("/store/{slug}/punch-events", response_model=list[PunchEventResponse])
async def list_punch_events(
    slug: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    query = select(PunchEvent).where(PunchEvent.store_id == ctx.store_id)
    if status is not None:
        query = query.where(PunchEvent.status == status)
    query = query.order_by(PunchEvent.punched_at_ms.desc()).limit(limit)
    return (await db.execute(query)).scalars().all()
