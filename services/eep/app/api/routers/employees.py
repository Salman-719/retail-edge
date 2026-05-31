"""Employee CRUD + section assignment endpoints."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.employee import Employee, EmployeeSection
from app.models.section import Section
from app.schemas.employees import (
    AssignSectionRequest,
    CreateEmployeeRequest,
    EmployeeResponse,
    EmployeeSectionItem,
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


async def _validate_section(section_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> None:
    result = await db.execute(
        select(Section).where(Section.id == section_id, Section.store_id == store_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=404,
            detail={"error": "Section not found in this store", "code": "SECTION_NOT_FOUND"},
        )


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


# ── Section assignment ────────────────────────────────────────────────────────

@router.get("/store/{slug}/employees/{employee_id}/sections", response_model=list[EmployeeSectionItem])
async def list_employee_sections(
    employee_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_employee_or_404(employee_id, ctx.store_id, db)
    result = await db.execute(
        select(EmployeeSection).where(EmployeeSection.employee_id == employee_id)
    )
    return result.scalars().all()


@router.post("/store/{slug}/employees/{employee_id}/sections", response_model=EmployeeSectionItem, status_code=201)
async def assign_employee_section(
    employee_id: uuid.UUID,
    body: AssignSectionRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_employee_or_404(employee_id, ctx.store_id, db)
    await _validate_section(body.section_id, ctx.store_id, db)

    existing = await db.execute(
        select(EmployeeSection).where(
            EmployeeSection.employee_id == employee_id,
            EmployeeSection.section_id == body.section_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": "Employee already assigned to this section", "code": "ALREADY_ASSIGNED"},
        )

    # If is_primary, clear existing primary
    if body.is_primary:
        existing_primary = await db.execute(
            select(EmployeeSection).where(
                EmployeeSection.employee_id == employee_id,
                EmployeeSection.is_primary == True,
            )
        )
        for es in existing_primary.scalars().all():
            es.is_primary = False

    es = EmployeeSection(
        employee_id=employee_id,
        section_id=body.section_id,
        is_primary=body.is_primary,
    )
    db.add(es)
    await db.flush()
    await write_audit_log(
        db, "employee_section_assigned", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="employee_section", entity_id=es.id,
        after_state={"section_id": str(body.section_id), "is_primary": body.is_primary},
    )
    await db.commit()
    return es


@router.delete("/store/{slug}/employees/{employee_id}/sections/{section_id}", status_code=204)
async def remove_employee_section(
    employee_id: uuid.UUID,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await _get_employee_or_404(employee_id, ctx.store_id, db)
    result = await db.execute(
        select(EmployeeSection).where(
            EmployeeSection.employee_id == employee_id,
            EmployeeSection.section_id == section_id,
        )
    )
    es = result.scalar_one_or_none()
    if not es:
        raise HTTPException(
            status_code=404,
            detail={"error": "Section assignment not found", "code": "NOT_FOUND"},
        )
    await db.delete(es)
    await db.commit()
