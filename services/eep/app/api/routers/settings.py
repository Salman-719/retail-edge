"""Store settings endpoints. (Alert config retired in D5 — see core/alert_defaults.py.)"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.store_settings import StoreSettings

router = APIRouter(tags=["settings"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class StoreSettingsResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    activation_countdown_sec: int
    chunk_duration_sec: int
    chunk_overlap_sec: int
    frame_sample_rate_fps: int
    active_config_cache_ttl_sec: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatchStoreSettingsRequest(BaseModel):
    activation_countdown_sec: Optional[int] = Field(None, ge=10, le=3600)
    chunk_duration_sec: Optional[int] = Field(None, ge=30, le=3600)
    chunk_overlap_sec: Optional[int] = Field(None, ge=0, le=300)
    frame_sample_rate_fps: Optional[int] = Field(None, ge=1, le=30)
    active_config_cache_ttl_sec: Optional[int] = Field(None, ge=10, le=86400)


# ── Store Settings endpoints ──────────────────────────────────────────────────

async def _get_settings_or_404(store_id: uuid.UUID, db: AsyncSession) -> StoreSettings:
    result = await db.execute(select(StoreSettings).where(StoreSettings.store_id == store_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Settings not found", "code": "NOT_FOUND"})
    return row


@router.get("/store/{slug}/settings", response_model=StoreSettingsResponse)
async def get_settings(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    return await _get_settings_or_404(ctx.store_id, db)


@router.patch("/store/{slug}/settings", response_model=StoreSettingsResponse)
async def patch_settings(
    body: PatchStoreSettingsRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    settings = await _get_settings_or_404(ctx.store_id, db)

    changed = False
    for field in body.model_fields:
        val = getattr(body, field)
        if val is not None:
            setattr(settings, field, val)
            changed = True

    if changed:
        settings.updated_at = datetime.now(timezone.utc)
        await write_audit_log(
            db, "config_edited", store_id=ctx.store_id, user_id=ctx.user_id,
            entity_type="store", entity_id=ctx.store_id,
        )
        await db.commit()

    return settings
