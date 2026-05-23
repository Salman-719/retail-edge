"""Audit log read endpoints."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.audit_log import AuditLog
from pydantic import BaseModel

router = APIRouter(tags=["audit"])


class AuditLogItem(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    action: str
    entity_type: Optional[str]
    entity_id: Optional[uuid.UUID]
    before_state: Optional[dict]
    after_state: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    page_size: int


@router.get("/store/{slug}/audit", response_model=AuditLogPage)
async def list_audit_log(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
):
    require_owner_or_manager(ctx)

    base = select(AuditLog).where(AuditLog.store_id == ctx.store_id)

    if action:
        base = base.where(AuditLog.action == action)
    if entity_type:
        base = base.where(AuditLog.entity_type == entity_type)
    if since:
        base = base.where(AuditLog.created_at >= since)
    if until:
        base = base.where(AuditLog.created_at <= until)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    rows = await db.execute(
        base.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
    )
    items = rows.scalars().all()

    return AuditLogPage(items=items, total=total, page=page, page_size=page_size)
