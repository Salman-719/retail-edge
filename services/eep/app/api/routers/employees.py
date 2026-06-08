"""Employee CRUD endpoints."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.employee import Employee
from app.schemas.employees import (
    CreateEmployeeRequest,
    EmployeeResponse,
    PatchEmployeeRequest,
)

router = APIRouter(tags=["employees"])


async def _get_employee_or_404(
    employee_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession
) -> Employee:
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.store_id == store_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise HTTPException(
            status_code=404,
            detail={"error": "Employee not found", "code": "NOT_FOUND"},
        )
    return emp


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/employees", response_model=list[EmployeeResponse])
async def list_employees(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    active_only: bool = True,
):
    require_owner_or_manager(ctx)
    query = select(Employee).where(Employee.store_id == ctx.store_id)
    if active_only:
        query = query.where(Employee.is_active == True)
    query = query.order_by(Employee.name)
    result = await db.execute(query)
    return result.scalars().all()


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/store/{slug}/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    body: CreateEmployeeRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    if body.employee_code:
        existing = await db.execute(
            select(Employee).where(
                Employee.store_id == ctx.store_id,
                Employee.employee_code == body.employee_code,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={"error": "employee_code already in use", "code": "CODE_CONFLICT"},
            )

    emp = Employee(
        store_id=ctx.store_id,
        name=body.name,
        role=body.role,
        employee_code=body.employee_code,
        phone=body.phone,
        email=str(body.email) if body.email else None,
    )
    db.add(emp)
    await db.flush()

    await write_audit_log(
        db, "employee_created", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="employee", entity_id=emp.id,
        after_state={"name": emp.name, "role": emp.role},
    )
    await db.commit()
    return emp


# ── Get ───────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/employees/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    return await _get_employee_or_404(employee_id, ctx.store_id, db)


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/store/{slug}/employees/{employee_id}", response_model=EmployeeResponse)
async def patch_employee(
    employee_id: uuid.UUID,
    request: Request,
    body: PatchEmployeeRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    emp = await _get_employee_or_404(employee_id, ctx.store_id, db)
    raw = await request.json()
    print("DEBUG patch_employee raw body:", raw, flush=True)

    if body.employee_code is not None and body.employee_code != emp.employee_code:
        existing = await db.execute(
            select(Employee).where(
                Employee.store_id == ctx.store_id,
                Employee.employee_code == body.employee_code,
                Employee.id != emp.id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail={"error": "employee_code already in use", "code": "CODE_CONFLICT"},
            )

    for field in ("name", "role", "employee_code", "phone", "email", "is_active", "enrollment_status"):
        if field not in raw:
            continue
        val = getattr(body, field)
        if field == "email" and val is not None:
            val = str(val)
        setattr(emp, field, val)

    emp.updated_at = datetime.now(timezone.utc)
    await write_audit_log(
        db, "employee_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="employee", entity_id=emp.id,
    )
    await db.commit()
    return emp


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/store/{slug}/employees/{employee_id}", status_code=204)
async def delete_employee(
    employee_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    emp = await _get_employee_or_404(employee_id, ctx.store_id, db)
    await db.delete(emp)
    await write_audit_log(
        db, "employee_deleted", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="employee", entity_id=employee_id,
    )
    await db.commit()
