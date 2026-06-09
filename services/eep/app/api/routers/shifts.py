"""Shift pattern CRUD, shift instance CRUD, assignments, breaks, and nightly generation."""
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.ratelimit import MAX_LIST_ROWS
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.employee import Employee
from app.models.shift_pattern import ShiftPattern
from app.models.shift_instance import BreakRecord, ShiftAssignment, ShiftInstance
from app.schemas.shifts import (
    AssignmentResponse,
    BreakResponse,
    CreateBreakRequest,
    CreateShiftInstanceRequest,
    CreateShiftPatternRequest,
    PatchAssignmentRequest,
    PatchBreakRequest,
    PatchShiftInstanceRequest,
    PatchShiftPatternRequest,
    ShiftInstanceResponse,
    ShiftPatternResponse,
)

router = APIRouter(tags=["shifts"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_employee_or_404(employee_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> Employee:
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.store_id == store_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail={"error": "Employee not found in this store", "code": "EMPLOYEE_NOT_FOUND"})
    return emp


async def _get_pattern_or_404(pattern_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> ShiftPattern:
    result = await db.execute(
        select(ShiftPattern)
        .join(Employee, Employee.id == ShiftPattern.employee_id)
        .where(ShiftPattern.id == pattern_id, Employee.store_id == store_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail={"error": "Shift pattern not found", "code": "NOT_FOUND"})
    return p


async def _get_instance_or_404(shift_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> ShiftInstance:
    result = await db.execute(
        select(ShiftInstance)
        .join(Employee, Employee.id == ShiftInstance.employee_id)
        .where(ShiftInstance.id == shift_id, Employee.store_id == store_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail={"error": "Shift not found", "code": "NOT_FOUND"})
    return s


async def _get_assignment_or_404(assignment_id: uuid.UUID, shift_id: uuid.UUID, db: AsyncSession) -> ShiftAssignment:
    result = await db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.id == assignment_id,
            ShiftAssignment.shift_id == shift_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail={"error": "Assignment not found", "code": "NOT_FOUND"})
    return a


async def _get_break_or_404(break_id: uuid.UUID, assignment_id: uuid.UUID, db: AsyncSession) -> BreakRecord:
    result = await db.execute(
        select(BreakRecord).where(
            BreakRecord.id == break_id,
            BreakRecord.assignment_id == assignment_id,
        )
    )
    b = result.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail={"error": "Break not found", "code": "NOT_FOUND"})
    return b


# ─────────────────────────────────────────────────────────────────────────────
# 49. Shift Pattern CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/shift-patterns", response_model=list[ShiftPatternResponse])
async def list_shift_patterns(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    active_only: bool = False,
    employee_id: uuid.UUID | None = None,
):
    require_owner_or_manager(ctx)
    query = (
        select(ShiftPattern)
        .join(Employee, Employee.id == ShiftPattern.employee_id)
        .where(Employee.store_id == ctx.store_id)
    )
    if active_only:
        query = query.where(ShiftPattern.is_active == True)
    if employee_id:
        query = query.where(ShiftPattern.employee_id == employee_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/store/{slug}/shift-patterns", response_model=ShiftPatternResponse, status_code=201)
async def create_shift_pattern(
    body: CreateShiftPatternRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_employee_or_404(body.employee_id, ctx.store_id, db)

    # Check for overlapping active pattern on the same employee + day
    existing_result = await db.execute(
        select(ShiftPattern).where(
            ShiftPattern.employee_id == body.employee_id,
            ShiftPattern.day_of_week == body.day_of_week,
            ShiftPattern.is_active == True,
        )
    )
    for existing in existing_result.scalars().all():
        if body.start_time < existing.end_time and body.end_time > existing.start_time:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Time overlaps with an existing shift pattern",
                    "code": "SHIFT_CONFLICT",
                    "conflicting_id": str(existing.id),
                    "conflicting_start": str(existing.start_time),
                    "conflicting_end": str(existing.end_time),
                },
            )

    pattern = ShiftPattern(
        employee_id=body.employee_id,
        day_of_week=body.day_of_week,
        start_time=body.start_time,
        end_time=body.end_time,
        break_duration_min=body.break_duration_min,
    )
    db.add(pattern)
    await db.flush()
    await write_audit_log(
        db, "shift_pattern_created", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_pattern", entity_id=pattern.id,
        after_state={"employee_id": str(body.employee_id), "day_of_week": body.day_of_week},
    )
    await db.commit()
    return pattern


@router.get("/store/{slug}/shift-patterns/{pattern_id}", response_model=ShiftPatternResponse)
async def get_shift_pattern(
    pattern_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    return await _get_pattern_or_404(pattern_id, ctx.store_id, db)


@router.patch("/store/{slug}/shift-patterns/{pattern_id}", response_model=ShiftPatternResponse)
async def patch_shift_pattern(
    pattern_id: uuid.UUID,
    body: PatchShiftPatternRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    pattern = await _get_pattern_or_404(pattern_id, ctx.store_id, db)

    if body.day_of_week is not None:
        pattern.day_of_week = body.day_of_week
    if body.start_time is not None:
        pattern.start_time = body.start_time
    if body.end_time is not None:
        pattern.end_time = body.end_time
    if body.break_duration_min is not None:
        pattern.break_duration_min = body.break_duration_min
    if body.is_active is not None:
        pattern.is_active = body.is_active

    if pattern.end_time <= pattern.start_time:
        raise HTTPException(
            status_code=422,
            detail={"error": "end_time must be after start_time", "code": "INVALID_TIME_RANGE"},
        )

    pattern.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        db, "shift_pattern_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_pattern", entity_id=pattern.id,
    )
    await db.commit()
    return pattern


@router.delete("/store/{slug}/shift-patterns/{pattern_id}", status_code=204)
async def delete_shift_pattern(
    pattern_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    pattern = await _get_pattern_or_404(pattern_id, ctx.store_id, db)
    await db.delete(pattern)
    await write_audit_log(
        db, "shift_pattern_deleted", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_pattern", entity_id=pattern_id,
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 50. Shift Instance CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/shifts", response_model=list[ShiftInstanceResponse])
async def list_shifts(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    from_date: date | None = None,
    to_date: date | None = None,
    employee_id: uuid.UUID | None = None,
):
    require_owner_or_manager(ctx)
    query = (
        select(ShiftInstance)
        .join(Employee, Employee.id == ShiftInstance.employee_id)
        .where(Employee.store_id == ctx.store_id)
    )
    if from_date:
        query = query.where(ShiftInstance.scheduled_start >= datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc))
    if to_date:
        end_dt = datetime(to_date.year, to_date.month, to_date.day, tzinfo=timezone.utc) + timedelta(days=1)
        query = query.where(ShiftInstance.scheduled_start < end_dt)
    if employee_id:
        query = query.where(ShiftInstance.employee_id == employee_id)
    query = query.order_by(ShiftInstance.scheduled_start).limit(MAX_LIST_ROWS)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/store/{slug}/shifts", response_model=ShiftInstanceResponse, status_code=201)
async def create_shift(
    body: CreateShiftInstanceRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_employee_or_404(body.employee_id, ctx.store_id, db)

    if body.shift_pattern_id is not None:
        await _get_pattern_or_404(body.shift_pattern_id, ctx.store_id, db)

    shift = ShiftInstance(
        employee_id=body.employee_id,
        shift_pattern_id=body.shift_pattern_id,
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
        break_duration_min=body.break_duration_min,
        status=body.status,
    )
    db.add(shift)
    await db.flush()
    await write_audit_log(
        db, "shift_created", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_instance", entity_id=shift.id,
        after_state={"scheduled_start": shift.scheduled_start.isoformat(), "scheduled_end": shift.scheduled_end.isoformat()},
    )
    await db.commit()
    return shift


@router.get("/store/{slug}/shifts/{shift_id}", response_model=ShiftInstanceResponse)
async def get_shift(
    shift_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    return await _get_instance_or_404(shift_id, ctx.store_id, db)


@router.patch("/store/{slug}/shifts/{shift_id}", response_model=ShiftInstanceResponse)
async def patch_shift(
    shift_id: uuid.UUID,
    body: PatchShiftInstanceRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    shift = await _get_instance_or_404(shift_id, ctx.store_id, db)

    if body.scheduled_start is not None:
        shift.scheduled_start = body.scheduled_start
    if body.scheduled_end is not None:
        shift.scheduled_end = body.scheduled_end
    if body.break_duration_min is not None:
        shift.break_duration_min = body.break_duration_min
    if body.actual_start is not None:
        shift.actual_start = body.actual_start
    if body.actual_end is not None:
        shift.actual_end = body.actual_end
    if body.status is not None:
        shift.status = body.status

    if shift.scheduled_end <= shift.scheduled_start:
        raise HTTPException(
            status_code=422,
            detail={"error": "scheduled_end must be after scheduled_start", "code": "INVALID_TIME_RANGE"},
        )

    shift.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        db, "shift_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_instance", entity_id=shift.id,
    )
    await db.commit()
    return shift


@router.delete("/store/{slug}/shifts/{shift_id}", status_code=204)
async def delete_shift(
    shift_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    shift = await _get_instance_or_404(shift_id, ctx.store_id, db)
    await db.delete(shift)
    await write_audit_log(
        db, "shift_deleted", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_instance", entity_id=shift_id,
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Assignments
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/shifts/{shift_id}/assignments", response_model=list[AssignmentResponse])
async def list_assignments(
    shift_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)
    result = await db.execute(
        select(ShiftAssignment).where(ShiftAssignment.shift_id == shift_id)
    )
    return result.scalars().all()


@router.post("/store/{slug}/shifts/{shift_id}/assignments", response_model=AssignmentResponse, status_code=201)
async def assign_employee(
    shift_id: uuid.UUID,
    body: dict,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)

    try:
        employee_id = uuid.UUID(str(body.get("employee_id", "")))
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "employee_id must be a valid UUID", "code": "INVALID_ID"})

    await _get_employee_or_404(employee_id, ctx.store_id, db)

    dup = await db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.employee_id == employee_id,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": "Employee already assigned to this shift", "code": "ALREADY_ASSIGNED"},
        )

    assignment = ShiftAssignment(shift_id=shift_id, employee_id=employee_id)
    db.add(assignment)
    await db.flush()
    await write_audit_log(
        db, "shift_employee_assigned", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_assignment", entity_id=assignment.id,
        after_state={"shift_id": str(shift_id), "employee_id": str(employee_id)},
    )
    await db.commit()
    return assignment


@router.patch(
    "/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}",
    response_model=AssignmentResponse,
)
async def patch_assignment(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: PatchAssignmentRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)
    assignment = await _get_assignment_or_404(assignment_id, shift_id, db)
    assignment.attendance_status = body.attendance_status
    await write_audit_log(
        db, "shift_attendance_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="shift_assignment", entity_id=assignment_id,
        after_state={"attendance_status": body.attendance_status},
    )
    await db.commit()
    return assignment


@router.delete("/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}", status_code=204)
async def remove_assignment(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)
    assignment = await _get_assignment_or_404(assignment_id, shift_id, db)
    await db.delete(assignment)
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 48. Break management
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}/breaks",
    response_model=list[BreakResponse],
)
async def list_breaks(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)
    await _get_assignment_or_404(assignment_id, shift_id, db)
    result = await db.execute(
        select(BreakRecord)
        .where(BreakRecord.assignment_id == assignment_id)
        .order_by(BreakRecord.break_start)
    )
    return result.scalars().all()


@router.post(
    "/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}/breaks",
    response_model=BreakResponse,
    status_code=201,
)
async def create_break(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: CreateBreakRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    shift = await _get_instance_or_404(shift_id, ctx.store_id, db)
    await _get_assignment_or_404(assignment_id, shift_id, db)

    if body.break_start < shift.scheduled_start or body.break_start >= shift.scheduled_end:
        raise HTTPException(
            status_code=422,
            detail={"error": "break_start must be within shift window", "code": "BREAK_OUT_OF_SHIFT"},
        )
    if body.break_end is not None and body.break_end > shift.scheduled_end:
        raise HTTPException(
            status_code=422,
            detail={"error": "break_end must not exceed shift end", "code": "BREAK_OUT_OF_SHIFT"},
        )

    br = BreakRecord(
        assignment_id=assignment_id,
        break_start=body.break_start,
        break_end=body.break_end,
        break_type=body.break_type,
    )
    db.add(br)
    await db.flush()
    await write_audit_log(
        db, "break_created", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="break_record", entity_id=br.id,
    )
    await db.commit()
    return br


@router.patch(
    "/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}/breaks/{break_id}",
    response_model=BreakResponse,
)
async def patch_break(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    break_id: uuid.UUID,
    body: PatchBreakRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    shift = await _get_instance_or_404(shift_id, ctx.store_id, db)
    await _get_assignment_or_404(assignment_id, shift_id, db)
    br = await _get_break_or_404(break_id, assignment_id, db)

    if body.break_end is not None:
        if body.break_end <= br.break_start:
            raise HTTPException(
                status_code=422,
                detail={"error": "break_end must be after break_start", "code": "INVALID_BREAK_RANGE"},
            )
        if body.break_end > shift.scheduled_end:
            raise HTTPException(
                status_code=422,
                detail={"error": "break_end must not exceed shift end", "code": "BREAK_OUT_OF_SHIFT"},
            )
        br.break_end = body.break_end

    if body.break_type is not None:
        br.break_type = body.break_type

    await db.commit()
    return br


@router.delete(
    "/store/{slug}/shifts/{shift_id}/assignments/{assignment_id}/breaks/{break_id}",
    status_code=204,
)
async def delete_break(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    break_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_instance_or_404(shift_id, ctx.store_id, db)
    await _get_assignment_or_404(assignment_id, shift_id, db)
    br = await _get_break_or_404(break_id, assignment_id, db)
    await db.delete(br)
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 51. Nightly job: generate shift instances from active patterns (7-day lookahead)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/store/{slug}/shifts/generate", status_code=200)
async def generate_shifts_from_patterns(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    lookahead_days: int = 7,
):
    """
    Generate shift instances for all active patterns for the next lookahead_days.
    Idempotent: skips dates that already have an instance from the same pattern.
    """
    require_owner_or_manager(ctx)

    patterns_result = await db.execute(
        select(ShiftPattern)
        .join(Employee, Employee.id == ShiftPattern.employee_id)
        .where(Employee.store_id == ctx.store_id, ShiftPattern.is_active == True)
    )
    patterns = patterns_result.scalars().all()

    today = datetime.now(timezone.utc).date()
    created_count = 0

    for pattern in patterns:
        for day_offset in range(lookahead_days):
            target_date = today + timedelta(days=day_offset)
            # DB uses 0=Mon … 6=Sun; Python isoweekday() is 1=Mon … 7=Sun
            if (target_date.isoweekday() - 1) != pattern.day_of_week:
                continue

            scheduled_start = datetime(
                target_date.year, target_date.month, target_date.day,
                pattern.start_time.hour, pattern.start_time.minute,
                tzinfo=timezone.utc,
            )
            scheduled_end = datetime(
                target_date.year, target_date.month, target_date.day,
                pattern.end_time.hour, pattern.end_time.minute,
                tzinfo=timezone.utc,
            )

            existing = await db.execute(
                select(ShiftInstance).where(
                    ShiftInstance.shift_pattern_id == pattern.id,
                    ShiftInstance.scheduled_start == scheduled_start,
                )
            )
            if existing.scalar_one_or_none():
                continue

            shift = ShiftInstance(
                employee_id=pattern.employee_id,
                shift_pattern_id=pattern.id,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                break_duration_min=pattern.break_duration_min,
                status="scheduled",
            )
            db.add(shift)
            created_count += 1

    await db.commit()
    return {"generated": created_count, "patterns_processed": len(patterns)}
