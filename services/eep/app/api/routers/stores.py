"""Store management endpoints."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.auth import get_current_user_payload
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.alert_config import AlertConfig
from app.models.store import Store
from app.models.store_settings import StoreSettings
from app.schemas.store import CreateStoreRequest, PatchStoreRequest, StoreDetail, StoreListItem

router = APIRouter(tags=["stores"])


@router.get("/stores", response_model=list[StoreListItem])
async def list_stores(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
):
    if payload.get("is_super_admin"):
        # Super-admin sees the whole fleet across all owners.
        # TODO pagination: unbounded select, fine while the fleet is small.
        result = await db.execute(select(Store).order_by(Store.name))
    elif payload.get("account_type") == "owner":
        user_id = uuid.UUID(payload["sub"])
        result = await db.execute(
            select(Store).where(Store.created_by == user_id).order_by(Store.name)
        )
    else:
        raise HTTPException(status_code=403, detail={"error": "Owner access required", "code": "OWNER_REQUIRED"})

    stores = result.scalars().all()

    items = []
    for s in stores:
        items.append(
            StoreListItem(
                id=s.id,
                name=s.name,
                slug=s.slug,
                status=s.status,
                active_version_label=None,  # populated in Phase 2
                camera_count=0,  # populated in Phase 2
            )
        )
    return items


@router.post("/stores", response_model=dict, status_code=201)
async def create_store(
    body: CreateStoreRequest,
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
):
    if payload.get("account_type") != "owner":
        raise HTTPException(status_code=403, detail={"error": "Owner access required", "code": "OWNER_REQUIRED"})

    user_id = uuid.UUID(payload["sub"])

    # Check slug uniqueness
    existing = await db.execute(select(Store).where(Store.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"error": "Slug already taken", "code": "SLUG_TAKEN"})

    store = Store(
        name=body.name,
        slug=body.slug,
        created_by=user_id,
        address=body.address,
    )
    db.add(store)
    await db.flush()

    # Auto-create store_settings with defaults
    db.add(StoreSettings(store_id=store.id))

    # Auto-create alert_configs with defaults
    db.add(AlertConfig(store_id=store.id))

    await write_audit_log(
        db, "store_created", store_id=store.id, user_id=user_id,
        entity_type="store", entity_id=store.id,
        after_state={"name": store.name, "slug": store.slug},
    )
    await db.commit()
    return {"store_id": str(store.id), "slug": store.slug}


@router.get("/store/{slug}/me")
async def get_my_context(ctx: StoreContext = Depends(get_store_context)):
    return {
        "role": "owner" if ctx.is_owner else ctx.role,
        "is_owner": ctx.is_owner,
        "permissions": list(ctx.permissions),
    }


@router.get("/store/{slug}", response_model=StoreDetail)
async def get_store(ctx: StoreContext = Depends(get_store_context)):
    s = ctx.store
    return StoreDetail(
        id=s.id,
        name=s.name,
        slug=s.slug,
        address=s.address,
        status=s.status,
        operating_hours=s.operating_hours,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.patch("/store/{slug}", response_model=StoreDetail)
async def patch_store(
    body: PatchStoreRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if not values:
        return await get_store(ctx)

    values["updated_at"] = datetime.now(timezone.utc)

    before = {k: getattr(ctx.store, k) for k in values if k != "updated_at"}
    await db.execute(update(Store).where(Store.id == ctx.store_id).values(**values))

    serializable_after = {k: v for k, v in values.items() if k != "updated_at"}
    serializable_before = {k: (str(v) if not isinstance(v, (str, int, float, bool, dict, list, type(None))) else v) for k, v in before.items()}
    await write_audit_log(
        db, "store_updated", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store", entity_id=ctx.store_id,
        before_state=serializable_before, after_state=serializable_after,
    )
    await db.commit()

    result = await db.execute(select(Store).where(Store.id == ctx.store_id))
    s = result.scalar_one()
    return StoreDetail(
        id=s.id, name=s.name, slug=s.slug,
        address=s.address, status=s.status,
        operating_hours=s.operating_hours, created_at=s.created_at, updated_at=s.updated_at,
    )


@router.delete("/store/{slug}", status_code=204)
async def delete_store(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.is_owner:
        raise HTTPException(status_code=403, detail={"error": "Only the store owner can delete a store", "code": "OWNER_REQUIRED"})

    await write_audit_log(
        db, "store_deleted", store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store", entity_id=ctx.store_id,
        before_state={"name": ctx.store.name, "slug": ctx.store.slug},
    )
    await db.execute(delete(Store).where(Store.id == ctx.store_id))
    await db.commit()
