"""Read-only store configuration endpoints (Phase 2)."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.s3_client import generate_presigned_url_public
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.models.camera_config import CameraConfig
from app.models.floor_plan import FloorPlan
from app.models.obstacle import Obstacle
from app.models.physical_camera import PhysicalCamera
from app.models.version import StoreConfigVersion
from app.models.version_sync_event import VersionSyncEvent
from app.models.zone import Zone
from app.schemas.config import (
    ActiveVersionResponse,
    CameraConfigSummary,
    FloorPlanResponse,
    ObstacleResponse,
    PhysicalCameraResponse,
    VersionListItem,
    ZoneResponse,
)

router = APIRouter(tags=["config"])


@router.get("/store/{slug}/versions", response_model=list[VersionListItem])
async def list_versions(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StoreConfigVersion)
        .where(StoreConfigVersion.store_id == ctx.store_id)
        .order_by(StoreConfigVersion.created_at.desc())
    )
    versions = result.scalars().all()

    # Attach the pending sync event id to draft versions
    items = []
    for v in versions:
        pending_event_id = None
        if v.status == "draft":
            ev_result = await db.execute(
                select(VersionSyncEvent.id)
                .where(
                    VersionSyncEvent.version_id == v.id,
                    VersionSyncEvent.status == "pending",
                )
                .order_by(VersionSyncEvent.scheduled_at.desc())
                .limit(1)
            )
            row = ev_result.scalar_one_or_none()
            if row:
                pending_event_id = row
        items.append(VersionListItem(
            id=v.id,
            label=v.label,
            status=v.status,
            active_from=v.active_from,
            active_until=v.active_until,
            created_at=v.created_at,
            pending_sync_event_id=pending_event_id,
        ))
    return items


@router.get("/store/{slug}/versions/active", response_model=ActiveVersionResponse)
async def get_active_version(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    version_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "active",
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail={"error": "No active version", "code": "NO_ACTIVE_VERSION"})

    # SPEC-00A: flattened — a store has exactly one floor plan, one set of
    # zones/obstacles, and one set of camera configs per version. No section loop.
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == version.id,
            FloorPlan.store_id == ctx.store_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    fp_response = None
    if fp:
        display_url = generate_presigned_url_public(fp.display_s3_key) if fp.display_s3_key else None
        fp_response = FloorPlanResponse(
            id=fp.id,
            version_id=fp.version_id,
            store_id=fp.store_id,
            onboarding_method=fp.onboarding_method,
            display_url=display_url,
            width_px=fp.width_px,
            height_px=fp.height_px,
            origin_x=fp.origin_x,
            origin_y=fp.origin_y,
            pixels_per_meter=fp.pixels_per_meter,
            world_x_min=fp.world_x_min,
            world_x_max=fp.world_x_max,
            world_y_min=fp.world_y_min,
            world_y_max=fp.world_y_max,
            image_uploaded=fp.image_uploaded,
            scale_defined=fp.scale_defined,
        )

    zones_result = await db.execute(
        select(Zone).where(Zone.version_id == version.id)
    )
    zones = [ZoneResponse.model_validate(z) for z in zones_result.scalars().all()]

    obstacles_result = await db.execute(
        select(Obstacle).where(Obstacle.version_id == version.id)
    )
    obstacles = [ObstacleResponse.model_validate(o) for o in obstacles_result.scalars().all()]

    configs_result = await db.execute(
        select(CameraConfig, PhysicalCamera)
        .join(PhysicalCamera, CameraConfig.physical_camera_id == PhysicalCamera.id)
        .where(CameraConfig.version_id == version.id)
    )
    camera_configs = []
    for cc, pc in configs_result.all():
        frame_url = generate_presigned_url_public(cc.frame_s3_key) if cc.frame_s3_key else None
        camera_configs.append(CameraConfigSummary(
            id=cc.id,
            physical_camera_id=cc.physical_camera_id,
            physical_camera_name=pc.name,
            store_id=cc.store_id,
            position_x=cc.position_x,
            position_y=cc.position_y,
            height_meters=cc.height_meters,
            fov_deg=cc.fov_deg,
            status=cc.status,
            frame_url=frame_url,
        ))

    return ActiveVersionResponse(
        id=version.id,
        label=version.label,
        status=version.status,
        active_from=version.active_from,
        floor_plan=fp_response,
        zones=zones,
        obstacles=obstacles,
        camera_configs=camera_configs,
    )


@router.get("/store/{slug}/cameras", response_model=list[PhysicalCameraResponse])
async def list_cameras(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PhysicalCamera)
        .where(PhysicalCamera.store_id == ctx.store_id, PhysicalCamera.is_active == True)
        .order_by(PhysicalCamera.created_at)
    )
    return result.scalars().all()


@router.post("/store/{slug}/versions/{version_id}/reactivate", response_model=VersionListItem)
async def reactivate_version(
    slug: str,
    version_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    version_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.id == version_id,
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "archived",
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=404,
            detail={"error": "Archived version not found", "code": "NOT_FOUND"},
        )

    draft_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "draft",
        )
    )
    if draft_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": "A draft exists; discard it before reactivating", "code": "DRAFT_EXISTS"},
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        update(StoreConfigVersion)
        .where(
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "active",
        )
        .values(status="archived", active_until=now)
    )
    version.status = "active"
    version.active_from = now
    version.active_until = None

    await write_audit_log(
        db, "version_activated",
        store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store_config_version", entity_id=version_id,
    )
    await db.commit()
    await db.refresh(version)

    # Recompute camera→zone coverage for the reactivated version so IEP3's
    # overlap graph reflects it. Non-fatal — reactivation must still succeed.
    try:
        from app.core.coverage import populate_camera_zone_coverage
        await populate_camera_zone_coverage(str(version_id))
    except Exception:
        logging.getLogger(__name__).exception(
            "reactivate_version: coverage population failed for version %s", version_id,
        )

    return version
