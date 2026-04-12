"""Employee CRUD endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import db as models
from app.schemas.employee import (
    EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    ShiftCreate, ShiftResponse,
)

router = APIRouter()


# ─── Employees ───────────────────────────────────────────────────────────────

@router.get("/{store_id}/employees", response_model=list[EmployeeResponse])
async def list_employees(store_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Employee).where(models.Employee.store_id == store_id)
    )
    return result.scalars().all()


@router.post("/{store_id}/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(store_id: str, payload: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")

    if payload.id:
        existing = await db.get(models.Employee, payload.id)
        if existing and existing.store_id == store_id:
            existing.name = payload.name
            if payload.role is not None:
                existing.role = payload.role
            await db.flush()
            await db.refresh(existing)
            return existing

    emp = models.Employee(
        id=payload.id,
        store_id=store_id,
        name=payload.name,
        role=payload.role,
    )
    db.add(emp)
    await db.flush()
    await db.refresh(emp)
    return emp


@router.get("/{store_id}/employees/{emp_id}", response_model=EmployeeResponse)
async def get_employee(store_id: str, emp_id: str, db: AsyncSession = Depends(get_db)):
    emp = await db.get(models.Employee, emp_id)
    if not emp or emp.store_id != store_id:
        raise HTTPException(404, "Employee not found")
    return emp


@router.put("/{store_id}/employees/{emp_id}", response_model=EmployeeResponse)
async def update_employee(store_id: str, emp_id: str, payload: EmployeeUpdate, db: AsyncSession = Depends(get_db)):
    emp = await db.get(models.Employee, emp_id)
    if not emp or emp.store_id != store_id:
        raise HTTPException(404, "Employee not found")
    if payload.name is not None:
        emp.name = payload.name
    if payload.role is not None:
        emp.role = payload.role
    await db.flush()
    await db.refresh(emp)
    return emp


@router.delete("/{store_id}/employees/{emp_id}", status_code=204)
async def delete_employee(store_id: str, emp_id: str, db: AsyncSession = Depends(get_db)):
    emp = await db.get(models.Employee, emp_id)
    if not emp or emp.store_id != store_id:
        raise HTTPException(404, "Employee not found")
    await db.delete(emp)


# ─── Shifts ──────────────────────────────────────────────────────────────────

@router.get("/{store_id}/employees/{emp_id}/shifts", response_model=list[ShiftResponse])
async def list_shifts(store_id: str, emp_id: str, db: AsyncSession = Depends(get_db)):
    emp = await db.get(models.Employee, emp_id)
    if not emp or emp.store_id != store_id:
        raise HTTPException(404, "Employee not found")
    result = await db.execute(
        select(models.Shift).where(models.Shift.employee_id == emp_id)
    )
    return result.scalars().all()


@router.post("/{store_id}/employees/{emp_id}/shifts", response_model=ShiftResponse, status_code=201)
async def create_shift(store_id: str, emp_id: str, payload: ShiftCreate, db: AsyncSession = Depends(get_db)):
    emp = await db.get(models.Employee, emp_id)
    if not emp or emp.store_id != store_id:
        raise HTTPException(404, "Employee not found")
    shift = models.Shift(
        employee_id=emp_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    db.add(shift)
    await db.flush()
    await db.refresh(shift)
    return shift
