"""Draft / onboarding wizard endpoints (Phase 3)."""
import io
import uuid
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core import s3_client, orchestrator
from app.middleware.store_auth import StoreContext, get_store_context, require_owner_or_manager
from app.tasks.camera_scheduler import mark_running, mark_stopped
from app.models.calibration import Calibration
from app.models.camera_config import CameraConfig
from app.models.floor_plan import FloorPlan
from app.models.obstacle import Obstacle
from app.models.physical_camera import PhysicalCamera
from app.models.section import Section
from app.models.version import StoreConfigVersion
from app.models.version_sync_event import VersionSyncEvent
from app.models.zone import Zone
from app.schemas.draft import (
    ActivateDraftRequest,
    CalibrationResponse,
    CameraConfigResponse,
    CreateCameraRequest,
    CreateDraftRequest,
    CreateSectionRequest,
    DraftVersionResponse,
    FloorPlanDetailResponse,
    FloorPlanUploadResponse,
    FrameUploadResponse,
    HomographyRequest,
    ObstacleCreate,
    ObstacleResponse,
    ObstacleUpdate,
    PatchCameraRequest,
    PatchSectionRequest,
    PhysicalCameraResponse,
    PlaceCameraConfigRequest,
    ScaleRequest,
    SectionResponse,
    SyncEventResponse,
    UpdateCameraConfigRequest,
    VersionActivateRequest,
    VersionActivateResponse,
    WorldBoundsRequest,
    ZoneCreate,
    ZoneResponse,
    ZoneUpdate,
)
from app.utils.homography import compute_homography
from app.utils.calibration_xml import parse_intrinsic_xml, parse_extrinsic_xml
from app.utils.shapely_utils import clamp_to_polygon, polygons_overlap
from app.core.redis_client import get_redis

router = APIRouter(tags=["draft"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_draft(store_id: uuid.UUID, db: AsyncSession) -> StoreConfigVersion | None:
    result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == store_id,
            StoreConfigVersion.status == "draft",
        )
    )
    return result.scalar_one_or_none()


async def _require_draft(store_id: uuid.UUID, db: AsyncSession) -> StoreConfigVersion:
    draft = await _get_draft(store_id, db)
    if not draft:
        raise HTTPException(status_code=404, detail={"error": "No draft exists", "code": "NO_DRAFT"})
    return draft


def _require_draft_access(draft: StoreConfigVersion, ctx: StoreContext) -> None:
    """Enforce that only the draft creator or store owner may edit."""
    if not ctx.is_owner and draft.created_by != ctx.user_id:
        raise HTTPException(status_code=403, detail={"error": "Not your draft", "code": "DRAFT_ACCESS_DENIED"})


async def _camera_config_response(cc: CameraConfig, db: AsyncSession) -> CameraConfigResponse:
    pc_result = await db.execute(select(PhysicalCamera).where(PhysicalCamera.id == cc.physical_camera_id))
    pc = pc_result.scalar_one()
    frame_url = s3_client.generate_presigned_url_public(cc.frame_s3_key) if cc.frame_s3_key else None
    return CameraConfigResponse(
        id=cc.id,
        version_id=cc.version_id,
        physical_camera_id=cc.physical_camera_id,
        physical_camera_name=pc.name,
        section_id=cc.section_id,
        position_x=cc.position_x,
        position_y=cc.position_y,
        height_meters=cc.height_meters,
        fov_deg=cc.fov_deg,
        stream_url=pc.cloud_stream_url,
        frame_url=frame_url,
        frame_captured_at=cc.frame_captured_at,
        status=cc.status,
    )


def _decode_image(content: bytes) -> tuple[int, int]:
    """Return (width, height) from raw image bytes using OpenCV."""
    arr = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=422, detail={"error": "Could not decode image", "code": "INVALID_IMAGE"})
    h, w = img.shape[:2]
    return w, h


# ─── Draft CRUD ───────────────────────────────────────────────────────────────

@router.get("/store/{slug}/versions/draft", response_model=DraftVersionResponse)
async def get_draft(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _get_draft(ctx.store_id, db)
    if not draft:
        raise HTTPException(status_code=404, detail={"error": "No draft", "code": "NO_DRAFT"})
    return draft


async def _clone_active_into_draft(draft_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> None:
    """Copy all data from the current active version into the new draft, duplicating S3 objects."""
    active_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == store_id,
            StoreConfigVersion.status == "active",
        )
    )
    active = active_result.scalar_one_or_none()
    if not active:
        return

    sections_result = await db.execute(
        select(Section).where(Section.store_id == store_id, Section.status == "active")
    )
    sections = sections_result.scalars().all()

    for section in sections:
        fp_result = await db.execute(
            select(FloorPlan).where(
                FloorPlan.version_id == active.id,
                FloorPlan.section_id == section.id,
            )
        )
        fp = fp_result.scalar_one_or_none()
        if fp:
            new_display_key = None
            new_original_key = None
            if fp.display_s3_key:
                ext = fp.display_s3_key.rsplit(".", 1)[-1]
                new_display_key = f"floor-plans/{store_id}/{section.id}/{uuid.uuid4()}.{ext}"
                try:
                    s3_client.copy_object(fp.display_s3_key, new_display_key)
                except Exception:
                    new_display_key = fp.display_s3_key
            if fp.original_s3_key and fp.original_s3_key != fp.display_s3_key:
                ext = fp.original_s3_key.rsplit(".", 1)[-1]
                new_original_key = f"floor-plans/{store_id}/{section.id}/{uuid.uuid4()}.{ext}"
                try:
                    s3_client.copy_object(fp.original_s3_key, new_original_key)
                except Exception:
                    new_original_key = fp.original_s3_key
            else:
                new_original_key = new_display_key
            db.add(FloorPlan(
                version_id=draft_id,
                section_id=section.id,
                onboarding_method=fp.onboarding_method,
                original_s3_key=new_original_key,
                display_s3_key=new_display_key,
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
            ))

        zones_result = await db.execute(
            select(Zone).where(Zone.version_id == active.id, Zone.section_id == section.id)
        )
        for zone in zones_result.scalars().all():
            db.add(Zone(
                version_id=draft_id,
                section_id=section.id,
                name=zone.name,
                type=zone.type,
                points=zone.points,
                queue_threshold_people=zone.queue_threshold_people,
                queue_threshold_minutes=zone.queue_threshold_minutes,
                staff_absence_minutes=zone.staff_absence_minutes,
            ))

        obstacles_result = await db.execute(
            select(Obstacle).where(Obstacle.version_id == active.id, Obstacle.section_id == section.id)
        )
        for obs in obstacles_result.scalars().all():
            db.add(Obstacle(
                version_id=draft_id,
                section_id=section.id,
                name=obs.name,
                points=obs.points,
            ))

        ccs_result = await db.execute(
            select(CameraConfig).where(
                CameraConfig.version_id == active.id,
                CameraConfig.section_id == section.id,
            ).order_by(CameraConfig.created_at.asc())
        )
        for cc in ccs_result.scalars().all():
            new_frame_key = None
            if cc.frame_s3_key:
                ext = cc.frame_s3_key.rsplit(".", 1)[-1]
                new_frame_key = f"camera-frames/{store_id}/{uuid.uuid4()}/{uuid.uuid4()}.{ext}"
                try:
                    s3_client.copy_object(cc.frame_s3_key, new_frame_key)
                except Exception:
                    new_frame_key = cc.frame_s3_key
            new_cc = CameraConfig(
                version_id=draft_id,
                physical_camera_id=cc.physical_camera_id,
                section_id=section.id,
                position_x=cc.position_x,
                position_y=cc.position_y,
                height_meters=cc.height_meters,
                fov_deg=cc.fov_deg,
                frame_s3_key=new_frame_key,
                frame_captured_at=cc.frame_captured_at,
                frame_source=cc.frame_source,
                status=cc.status,
            )
            db.add(new_cc)
            await db.flush()

            cals_result = await db.execute(
                select(Calibration)
                .where(Calibration.camera_config_id == cc.id)
                .order_by(Calibration.created_at.asc())
            )
            for cal in cals_result.scalars().all():
                new_intrinsic_key = None
                new_extrinsic_key = None
                if cal.intrinsic_file_s3_key:
                    new_intrinsic_key = f"calibration-files/{store_id}/{new_cc.id}/intrinsic.xml"
                    try:
                        s3_client.copy_object(cal.intrinsic_file_s3_key, new_intrinsic_key)
                    except Exception:
                        new_intrinsic_key = cal.intrinsic_file_s3_key
                if cal.extrinsic_file_s3_key:
                    new_extrinsic_key = f"calibration-files/{store_id}/{new_cc.id}/extrinsic.xml"
                    try:
                        s3_client.copy_object(cal.extrinsic_file_s3_key, new_extrinsic_key)
                    except Exception:
                        new_extrinsic_key = cal.extrinsic_file_s3_key
                db.add(Calibration(
                    camera_config_id=new_cc.id,
                    method=cal.method,
                    status=cal.status,
                    is_current=cal.is_current,
                    correspondences=cal.correspondences,
                    homography_matrix=cal.homography_matrix,
                    rms_reprojection_error=cal.rms_reprojection_error,
                    max_reprojection_error=cal.max_reprojection_error,
                    point_count=cal.point_count,
                    coverage_score=cal.coverage_score,
                    condition_number=cal.condition_number,
                    intrinsic_file_s3_key=new_intrinsic_key,
                    extrinsic_file_s3_key=new_extrinsic_key,
                    intrinsic_matrix=cal.intrinsic_matrix,
                    dist_coeffs=cal.dist_coeffs,
                    rotation_vector=cal.rotation_vector,
                    rotation_matrix=cal.rotation_matrix,
                    translation_vector=cal.translation_vector,
                    camera_world_x=cal.camera_world_x,
                    camera_world_y=cal.camera_world_y,
                    camera_world_z=cal.camera_world_z,
                    image_width=cal.image_width,
                    image_height=cal.image_height,
                    computed_at=cal.computed_at,
                    verified_at=cal.verified_at,
                    verified_by=cal.verified_by,
                ))


@router.post("/store/{slug}/versions/draft", response_model=DraftVersionResponse, status_code=201)
async def create_draft(
    body: CreateDraftRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)

    existing = await _get_draft(ctx.store_id, db)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "A draft already exists",
                "code": "DRAFT_EXISTS",
                "draft_created_by": str(existing.created_by),
            },
        )

    draft = StoreConfigVersion(
        store_id=ctx.store_id,
        label=body.label,
        status="draft",
        created_by=ctx.user_id,
    )
    db.add(draft)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _get_draft(ctx.store_id, db)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "A draft already exists",
                "code": "DRAFT_EXISTS",
                "draft_created_by": str(existing.created_by) if existing else None,
            },
        )

    if body.clone_from_active:
        await _clone_active_into_draft(draft.id, ctx.store_id, db)

    await write_audit_log(
        db, "draft_created",
        store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store_config_version", entity_id=draft.id,
    )
    await db.commit()
    await db.refresh(draft)
    return draft


@router.delete("/store/{slug}/versions/draft", status_code=204)
async def delete_draft(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    # Clean up all S3 objects attached to this draft
    await _cleanup_draft_s3(draft.id, ctx.store_id, db)

    await db.delete(draft)
    await write_audit_log(
        db, "draft_discarded",
        store_id=ctx.store_id, user_id=ctx.user_id,
        entity_type="store_config_version", entity_id=draft.id,
    )
    await db.commit()


async def _cleanup_draft_s3(version_id: uuid.UUID, store_id: uuid.UUID, db: AsyncSession) -> None:
    """Delete all S3 objects belonging to a draft version."""
    fps = await db.execute(select(FloorPlan).where(FloorPlan.version_id == version_id))
    for fp in fps.scalars().all():
        if fp.display_s3_key:
            try:
                s3_client.delete_object(fp.display_s3_key)
            except Exception:
                pass

    ccs = await db.execute(select(CameraConfig).where(CameraConfig.version_id == version_id))
    for cc in ccs.scalars().all():
        if cc.frame_s3_key:
            try:
                s3_client.delete_object(cc.frame_s3_key)
            except Exception:
                pass
        cals = await db.execute(
            select(Calibration).where(Calibration.camera_config_id == cc.id)
        )
        for cal in cals.scalars().all():
            for key in (cal.intrinsic_file_s3_key, cal.extrinsic_file_s3_key):
                if key:
                    try:
                        s3_client.delete_object(key)
                    except Exception:
                        pass


# ─── Floor Plan ───────────────────────────────────────────────────────────────

@router.post(
    "/store/{slug}/draft/sections/{section_id}/floor-plan/upload",
    response_model=FloorPlanUploadResponse,
)
async def upload_floor_plan(
    slug: str,
    section_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    content = await file.read()
    width, height = _decode_image(content)

    ext = (file.filename or "image.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        ext = "jpg"
    s3_key = f"floor-plans/{ctx.store_id}/{section_id}/{uuid.uuid4()}.{ext}"
    content_type = file.content_type or "image/jpeg"
    s3_client.upload_bytes(content, s3_key, content_type)

    # Find existing floor plan — wipe downstream on re-upload
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()

    if fp:
        # Delete old image from S3
        if fp.display_s3_key and fp.display_s3_key != s3_key:
            try:
                s3_client.delete_object(fp.display_s3_key)
            except Exception:
                pass
        # Cascade wipe: zones, obstacles, camera configs for this section/version
        await db.execute(delete(Zone).where(Zone.version_id == draft.id, Zone.section_id == section_id))
        await db.execute(delete(Obstacle).where(Obstacle.version_id == draft.id, Obstacle.section_id == section_id))
        cc_result = await db.execute(
            select(CameraConfig).where(
                CameraConfig.version_id == draft.id,
                CameraConfig.section_id == section_id,
            )
        )
        for cc in cc_result.scalars().all():
            if cc.frame_s3_key:
                try:
                    s3_client.delete_object(cc.frame_s3_key)
                except Exception:
                    pass
        await db.execute(
            delete(CameraConfig).where(
                CameraConfig.version_id == draft.id,
                CameraConfig.section_id == section_id,
            )
        )
        fp.original_s3_key = s3_key
        fp.display_s3_key = s3_key
        fp.width_px = width
        fp.height_px = height
        fp.image_uploaded = True
        fp.scale_defined = False
        fp.origin_x = None
        fp.origin_y = None
        fp.pixels_per_meter = None
        fp.world_x_min = None
        fp.world_x_max = None
        fp.world_y_min = None
        fp.world_y_max = None
        fp.updated_at = datetime.now(timezone.utc)
    else:
        fp = FloorPlan(
            version_id=draft.id,
            section_id=section_id,
            onboarding_method="standard",
            original_s3_key=s3_key,
            display_s3_key=s3_key,
            width_px=width,
            height_px=height,
            image_uploaded=True,
            scale_defined=False,
        )
        db.add(fp)

    await db.commit()
    await db.refresh(fp)

    display_url = s3_client.generate_presigned_url_public(s3_key)
    return FloorPlanUploadResponse(
        id=fp.id,
        version_id=fp.version_id,
        section_id=fp.section_id,
        onboarding_method=fp.onboarding_method,
        display_url=display_url,
        width_px=fp.width_px,
        height_px=fp.height_px,
        image_uploaded=fp.image_uploaded,
        scale_defined=fp.scale_defined,
    )


@router.get(
    "/store/{slug}/draft/sections/{section_id}/floor-plan",
    response_model=FloorPlanDetailResponse,
)
async def get_draft_floor_plan(
    slug: str,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    if not fp:
        raise HTTPException(status_code=404, detail={"error": "Floor plan not found", "code": "NO_FLOOR_PLAN"})

    display_url = s3_client.generate_presigned_url_public(fp.display_s3_key) if fp.display_s3_key else None
    return FloorPlanDetailResponse(
        id=fp.id,
        version_id=fp.version_id,
        section_id=fp.section_id,
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
        boundary_polygon=fp.boundary_polygon,
        image_uploaded=fp.image_uploaded,
        scale_defined=fp.scale_defined,
    )


@router.put(
    "/store/{slug}/draft/sections/{section_id}/floor-plan/scale",
    response_model=FloorPlanDetailResponse,
)
async def set_floor_plan_scale(
    slug: str,
    section_id: uuid.UUID,
    body: ScaleRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    if not fp or not fp.image_uploaded:
        raise HTTPException(status_code=404, detail={"error": "Floor plan not found or image not uploaded", "code": "NO_FLOOR_PLAN"})

    p1 = np.array(body.ref_point_1)
    p2 = np.array(body.ref_point_2)
    pixel_distance = float(np.linalg.norm(p2 - p1))
    if pixel_distance < 1e-6:
        raise HTTPException(status_code=422, detail={"error": "Reference points are identical", "code": "IDENTICAL_POINTS"})

    pixels_per_meter = pixel_distance / body.real_distance_meters

    fp.origin_x = body.origin_x
    fp.origin_y = body.origin_y
    fp.pixels_per_meter = pixels_per_meter
    fp.scale_defined = True
    if body.boundary_polygon is not None:
        fp.boundary_polygon = body.boundary_polygon if len(body.boundary_polygon) >= 3 else None
    fp.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(fp)

    display_url = s3_client.generate_presigned_url_public(fp.display_s3_key) if fp.display_s3_key else None
    return FloorPlanDetailResponse(
        id=fp.id, version_id=fp.version_id, section_id=fp.section_id,
        onboarding_method=fp.onboarding_method, display_url=display_url,
        width_px=fp.width_px, height_px=fp.height_px,
        origin_x=fp.origin_x, origin_y=fp.origin_y,
        pixels_per_meter=fp.pixels_per_meter,
        world_x_min=fp.world_x_min, world_x_max=fp.world_x_max,
        world_y_min=fp.world_y_min, world_y_max=fp.world_y_max,
        boundary_polygon=fp.boundary_polygon,
        image_uploaded=fp.image_uploaded, scale_defined=fp.scale_defined,
    )


@router.put(
    "/store/{slug}/draft/sections/{section_id}/floor-plan/world-bounds",
    response_model=FloorPlanDetailResponse,
)
async def set_floor_plan_boundary_polygon(
    slug: str,
    section_id: uuid.UUID,
    body: WorldBoundsRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    if not fp:
        raise HTTPException(status_code=404, detail={"error": "Floor plan not found", "code": "NO_FLOOR_PLAN"})

    fp.world_x_min = body.world_x_min
    fp.world_x_max = body.world_x_max
    fp.world_y_min = body.world_y_min
    fp.world_y_max = body.world_y_max
    fp.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(fp)

    display_url = s3_client.generate_presigned_url_public(fp.display_s3_key) if fp.display_s3_key else None
    return FloorPlanDetailResponse(
        id=fp.id, version_id=fp.version_id, section_id=fp.section_id,
        onboarding_method=fp.onboarding_method, display_url=display_url,
        width_px=fp.width_px, height_px=fp.height_px,
        origin_x=fp.origin_x, origin_y=fp.origin_y,
        pixels_per_meter=fp.pixels_per_meter,
        world_x_min=fp.world_x_min, world_x_max=fp.world_x_max,
        world_y_min=fp.world_y_min, world_y_max=fp.world_y_max,
        boundary_polygon=fp.boundary_polygon,
        image_uploaded=fp.image_uploaded, scale_defined=fp.scale_defined,
    )


# ─── Zones ────────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/draft/sections/{section_id}/zones", response_model=list[ZoneResponse])
async def list_draft_zones(
    slug: str,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    result = await db.execute(
        select(Zone).where(Zone.version_id == draft.id, Zone.section_id == section_id)
    )
    return result.scalars().all()


@router.post(
    "/store/{slug}/draft/sections/{section_id}/zones",
    response_model=ZoneResponse,
    status_code=201,
)
async def create_zone(
    slug: str,
    section_id: uuid.UUID,
    body: ZoneCreate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    # Require scale to be defined before zones can be drawn
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    if not fp or not fp.scale_defined:
        raise HTTPException(
            status_code=422,
            detail={"error": "Floor plan scale must be set before drawing zones", "code": "SCALE_NOT_DEFINED"},
        )

    # Validate all zone points are within floor plan bounds
    for point in body.points:
        if not (0 <= point[0] <= fp.width_px and 0 <= point[1] <= fp.height_px):
            raise HTTPException(
                status_code=422,
                detail={"error": f"Point {point} is outside floor plan bounds ({fp.width_px}x{fp.height_px})", "code": "POINT_OUT_OF_BOUNDS"},
            )

    # Check for name uniqueness within this section/version
    existing_name = await db.execute(
        select(Zone).where(
            Zone.version_id == draft.id,
            Zone.section_id == section_id,
            Zone.name == body.name,
        )
    )
    if existing_name.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"error": "Zone name already exists", "code": "ZONE_NAME_TAKEN"})

    # Check polygon overlap with existing zones
    existing_zones = await db.execute(
        select(Zone).where(Zone.version_id == draft.id, Zone.section_id == section_id)
    )
    for existing in existing_zones.scalars().all():
        if polygons_overlap(body.points, existing.points):
            raise HTTPException(
                status_code=422,
                detail={"error": f"Zone overlaps with '{existing.name}'", "code": "ZONE_OVERLAP"},
            )

    zone = Zone(
        version_id=draft.id,
        section_id=section_id,
        name=body.name,
        type=body.type,
        points=body.points,
        queue_threshold_people=body.queue_threshold_people,
        queue_threshold_minutes=body.queue_threshold_minutes,
        staff_absence_minutes=body.staff_absence_minutes,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return zone


@router.put(
    "/store/{slug}/draft/sections/{section_id}/zones/{zone_id}",
    response_model=ZoneResponse,
)
async def update_zone(
    slug: str,
    section_id: uuid.UUID,
    zone_id: uuid.UUID,
    body: ZoneUpdate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    result = await db.execute(
        select(Zone).where(
            Zone.id == zone_id,
            Zone.version_id == draft.id,
            Zone.section_id == section_id,
        )
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail={"error": "Zone not found", "code": "NOT_FOUND"})

    new_points = body.points if body.points is not None else zone.points

    if body.points is not None:
        fp_result = await db.execute(
            select(FloorPlan).where(
                FloorPlan.version_id == draft.id,
                FloorPlan.section_id == section_id,
            )
        )
        fp = fp_result.scalar_one_or_none()
        if fp:
            for point in body.points:
                if not (0 <= point[0] <= fp.width_px and 0 <= point[1] <= fp.height_px):
                    raise HTTPException(
                        status_code=422,
                        detail={"error": f"Point {point} is outside floor plan bounds ({fp.width_px}x{fp.height_px})", "code": "POINT_OUT_OF_BOUNDS"},
                    )

        existing_zones = await db.execute(
            select(Zone).where(
                Zone.version_id == draft.id,
                Zone.section_id == section_id,
                Zone.id != zone_id,
            )
        )
        for existing in existing_zones.scalars().all():
            if polygons_overlap(new_points, existing.points):
                raise HTTPException(
                    status_code=422,
                    detail={"error": f"Zone overlaps with '{existing.name}'", "code": "ZONE_OVERLAP"},
                )

    if body.name is not None:
        zone.name = body.name
    if body.type is not None:
        zone.type = body.type
    if body.points is not None:
        zone.points = body.points
    if body.queue_threshold_people is not None:
        zone.queue_threshold_people = body.queue_threshold_people
    if body.queue_threshold_minutes is not None:
        zone.queue_threshold_minutes = body.queue_threshold_minutes
    if body.staff_absence_minutes is not None:
        zone.staff_absence_minutes = body.staff_absence_minutes
    zone.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(zone)
    return zone


@router.delete("/store/{slug}/draft/sections/{section_id}/zones/{zone_id}", status_code=204)
async def delete_zone(
    slug: str,
    section_id: uuid.UUID,
    zone_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)
    await db.execute(
        delete(Zone).where(
            Zone.id == zone_id,
            Zone.version_id == draft.id,
            Zone.section_id == section_id,
        )
    )
    await db.commit()


# ─── Obstacles ────────────────────────────────────────────────────────────────

@router.get("/store/{slug}/draft/sections/{section_id}/obstacles", response_model=list[ObstacleResponse])
async def list_draft_obstacles(
    slug: str,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    result = await db.execute(
        select(Obstacle).where(Obstacle.version_id == draft.id, Obstacle.section_id == section_id)
    )
    return result.scalars().all()


@router.post(
    "/store/{slug}/draft/sections/{section_id}/obstacles",
    response_model=ObstacleResponse,
    status_code=201,
)
async def create_obstacle(
    slug: str,
    section_id: uuid.UUID,
    body: ObstacleCreate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)
    obstacle = Obstacle(
        version_id=draft.id,
        section_id=section_id,
        name=body.name,
        points=body.points,
    )
    db.add(obstacle)
    await db.commit()
    await db.refresh(obstacle)
    return obstacle


@router.put(
    "/store/{slug}/draft/sections/{section_id}/obstacles/{obstacle_id}",
    response_model=ObstacleResponse,
)
async def update_obstacle(
    slug: str,
    section_id: uuid.UUID,
    obstacle_id: uuid.UUID,
    body: ObstacleUpdate,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    result = await db.execute(
        select(Obstacle).where(
            Obstacle.id == obstacle_id,
            Obstacle.version_id == draft.id,
            Obstacle.section_id == section_id,
        )
    )
    obstacle = result.scalar_one_or_none()
    if not obstacle:
        raise HTTPException(status_code=404, detail={"error": "Obstacle not found", "code": "NOT_FOUND"})

    if body.name is not None:
        obstacle.name = body.name
    if body.points is not None:
        obstacle.points = body.points
    obstacle.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(obstacle)
    return obstacle


@router.delete("/store/{slug}/draft/sections/{section_id}/obstacles/{obstacle_id}", status_code=204)
async def delete_obstacle(
    slug: str,
    section_id: uuid.UUID,
    obstacle_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)
    await db.execute(
        delete(Obstacle).where(
            Obstacle.id == obstacle_id,
            Obstacle.version_id == draft.id,
            Obstacle.section_id == section_id,
        )
    )
    await db.commit()


# ─── Physical Cameras ─────────────────────────────────────────────────────────

@router.post("/store/{slug}/cameras", response_model=PhysicalCameraResponse, status_code=201)
async def create_camera(
    slug: str,
    body: CreateCameraRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    camera = PhysicalCamera(
        store_id=ctx.store_id,
        name=body.name,
        brand=body.brand,
        model=body.model,
        mounting=body.mounting or "ceiling",
        cloud_stream_url=body.cloud_stream_url,
        stream_username=body.stream_username,
        stream_password=body.stream_password,
    )
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return camera


@router.patch("/store/{slug}/cameras/{camera_id}", response_model=PhysicalCameraResponse)
async def patch_camera(
    slug: str,
    camera_id: uuid.UUID,
    body: PatchCameraRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    result = await db.execute(
        select(PhysicalCamera).where(
            PhysicalCamera.id == camera_id,
            PhysicalCamera.store_id == ctx.store_id,
        )
    )
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail={"error": "Camera not found", "code": "NOT_FOUND"})

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(camera, field, value)
    camera.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(camera)
    return camera


@router.delete("/store/{slug}/cameras/{camera_id}", status_code=204)
async def delete_camera(
    slug: str,
    camera_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    await db.execute(
        update(PhysicalCamera)
        .where(PhysicalCamera.id == camera_id, PhysicalCamera.store_id == ctx.store_id)
        .values(is_active=False, updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


# ─── Camera Configs ───────────────────────────────────────────────────────────

@router.get(
    "/store/{slug}/draft/sections/{section_id}/camera-configs",
    response_model=list[CameraConfigResponse],
)
async def list_draft_camera_configs(
    slug: str,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.version_id == draft.id,
            CameraConfig.section_id == section_id,
        ).order_by(CameraConfig.created_at.asc())
    )
    configs = result.scalars().all()
    return [await _camera_config_response(cc, db) for cc in configs]


@router.post(
    "/store/{slug}/draft/sections/{section_id}/camera-configs",
    response_model=CameraConfigResponse,
    status_code=201,
)
async def place_camera_config(
    slug: str,
    section_id: uuid.UUID,
    body: PlaceCameraConfigRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    # Verify camera belongs to this store and is active
    pc_result = await db.execute(
        select(PhysicalCamera).where(
            PhysicalCamera.id == body.physical_camera_id,
            PhysicalCamera.store_id == ctx.store_id,
            PhysicalCamera.is_active == True,
        )
    )
    if not pc_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": "Camera not found", "code": "CAMERA_NOT_FOUND"})

    # Enforce one placement per camera per version
    existing = await db.execute(
        select(CameraConfig).where(
            CameraConfig.version_id == draft.id,
            CameraConfig.physical_camera_id == body.physical_camera_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": "Camera already placed in this draft", "code": "CAMERA_ALREADY_PLACED"},
        )

    cc = CameraConfig(
        version_id=draft.id,
        physical_camera_id=body.physical_camera_id,
        section_id=section_id,
        position_x=body.position_x,
        position_y=body.position_y,
        height_meters=body.height_meters,
        fov_deg=body.fov_deg,
    )
    db.add(cc)
    await db.commit()
    await db.refresh(cc)
    return await _camera_config_response(cc, db)


@router.put(
    "/store/{slug}/draft/camera-configs/{config_id}",
    response_model=CameraConfigResponse,
)
async def update_camera_config(
    slug: str,
    config_id: uuid.UUID,
    body: UpdateCameraConfigRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.id == config_id,
            CameraConfig.version_id == draft.id,
        )
    )
    cc = result.scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail={"error": "Camera config not found", "code": "NOT_FOUND"})

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cc, field, value)
    cc.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(cc)
    return await _camera_config_response(cc, db)


@router.delete("/store/{slug}/draft/camera-configs/{config_id}", status_code=204)
async def delete_camera_config(
    slug: str,
    config_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.id == config_id,
            CameraConfig.version_id == draft.id,
        )
    )
    cc = result.scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail={"error": "Camera config not found", "code": "NOT_FOUND"})

    if cc.frame_s3_key:
        try:
            s3_client.delete_object(cc.frame_s3_key)
        except Exception:
            pass

    await db.execute(delete(CameraConfig).where(CameraConfig.id == config_id))
    await db.commit()


# ─── Camera Frame Upload ──────────────────────────────────────────────────────

@router.post(
    "/store/{slug}/draft/camera-configs/{config_id}/frame",
    response_model=FrameUploadResponse,
)
async def upload_camera_frame(
    slug: str,
    config_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.id == config_id,
            CameraConfig.version_id == draft.id,
        )
    )
    cc = result.scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail={"error": "Camera config not found", "code": "NOT_FOUND"})

    content = await file.read()
    _decode_image(content)  # validate image

    ext = (file.filename or "frame.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        ext = "jpg"
    s3_key = f"camera-frames/{ctx.store_id}/{config_id}/{uuid.uuid4()}.{ext}"
    s3_client.upload_bytes(content, s3_key, file.content_type or "image/jpeg")

    # Delete old frame
    if cc.frame_s3_key and cc.frame_s3_key != s3_key:
        try:
            s3_client.delete_object(cc.frame_s3_key)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    cc.frame_s3_key = s3_key
    cc.frame_captured_at = now
    cc.frame_source = "manual"
    cc.status = "frame_uploaded"
    cc.updated_at = now

    await db.commit()

    frame_url = s3_client.generate_presigned_url_public(s3_key)
    return FrameUploadResponse(
        config_id=cc.id,
        frame_url=frame_url,
        frame_captured_at=now,
        status=cc.status,
    )


# ─── Calibration ──────────────────────────────────────────────────────────────

@router.get(
    "/store/{slug}/draft/camera-configs/{config_id}/calibrations",
    response_model=list[CalibrationResponse],
)
async def list_calibrations(
    slug: str,
    config_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    result = await db.execute(
        select(Calibration)
        .where(Calibration.camera_config_id == config_id)
        .order_by(Calibration.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/store/{slug}/draft/camera-configs/{config_id}/calibration/homography",
    response_model=CalibrationResponse,
    status_code=201,
)
async def compute_homography_calibration(
    slug: str,
    config_id: uuid.UUID,
    body: HomographyRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    cc_result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.id == config_id,
            CameraConfig.version_id == draft.id,
        )
    )
    cc = cc_result.scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail={"error": "Camera config not found", "code": "NOT_FOUND"})

    corr_list = [{"pixel": c.pixel, "world": c.world} for c in body.correspondences]
    try:
        result = compute_homography(corr_list)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "HOMOGRAPHY_FAILED"})

    if result["coverage_score"] < 0.25:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Points are too clustered (coverage {result['coverage_score']:.2f} < 0.25). "
                    "Add more points spread across different areas of the camera frame."
                ),
                "code": "POOR_COVERAGE",
            },
        )

    now = datetime.now(timezone.utc)

    # Demote any prior current calibration for this config
    await db.execute(
        update(Calibration)
        .where(Calibration.camera_config_id == config_id, Calibration.is_current == True)
        .values(is_current=False)
    )

    cal = Calibration(
        camera_config_id=config_id,
        method="homography",
        status="ok",
        is_current=True,
        correspondences=corr_list,
        homography_matrix=result["homography_matrix"],
        rms_reprojection_error=result["rms_reprojection_error"],
        max_reprojection_error=result["max_reprojection_error"],
        point_count=result["point_count"],
        coverage_score=result["coverage_score"],
        condition_number=result["condition_number"],
        computed_at=now,
    )
    db.add(cal)

    cc.status = "calibrated"
    cc.updated_at = now

    await db.commit()
    await db.refresh(cal)

    # R5 (M5-S1): signal IEP2 to reload homography without pod restart
    try:
        await redis.publish(f"iep2:reload:{config_id}", "homography")
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Failed to publish homography reload signal  config_id=%s: %s", config_id, exc
        )

    return cal


@router.post(
    "/store/{slug}/draft/camera-configs/{config_id}/calibration/files",
    response_model=CalibrationResponse,
    status_code=201,
)
async def upload_calibration_files(
    slug: str,
    config_id: uuid.UUID,
    intrinsic: UploadFile = File(...),
    extrinsic: UploadFile | None = File(None),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    cc_result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.id == config_id,
            CameraConfig.version_id == draft.id,
        )
    )
    cc = cc_result.scalar_one_or_none()
    if not cc:
        raise HTTPException(status_code=404, detail={"error": "Camera config not found", "code": "NOT_FOUND"})

    intrinsic_content = await intrinsic.read()
    try:
        intrinsic_data = parse_intrinsic_xml(intrinsic_content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"error": f"Invalid intrinsic XML: {exc}", "code": "INVALID_XML"})

    extrinsic_data: dict = {}
    extrinsic_s3_key: str | None = None
    if extrinsic:
        extrinsic_content = await extrinsic.read()
        try:
            extrinsic_data = parse_extrinsic_xml(extrinsic_content)
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": f"Invalid extrinsic XML: {exc}", "code": "INVALID_XML"})
        extrinsic_s3_key = f"calibration-files/{ctx.store_id}/{config_id}/extrinsic.xml"
        s3_client.upload_bytes(extrinsic_content, extrinsic_s3_key, "application/xml")

    intrinsic_s3_key = f"calibration-files/{ctx.store_id}/{config_id}/intrinsic.xml"
    s3_client.upload_bytes(intrinsic_content, intrinsic_s3_key, "application/xml")

    now = datetime.now(timezone.utc)

    # Demote any prior current calibration
    await db.execute(
        update(Calibration)
        .where(Calibration.camera_config_id == config_id, Calibration.is_current == True)
        .values(is_current=False)
    )

    cal = Calibration(
        camera_config_id=config_id,
        method="calibration_files",
        status="ok",
        is_current=True,
        intrinsic_file_s3_key=intrinsic_s3_key,
        extrinsic_file_s3_key=extrinsic_s3_key,
        intrinsic_matrix=intrinsic_data.get("intrinsic_matrix"),
        dist_coeffs=intrinsic_data.get("dist_coeffs"),
        image_width=intrinsic_data.get("image_width"),
        image_height=intrinsic_data.get("image_height"),
        rotation_vector=extrinsic_data.get("rotation_vector"),
        rotation_matrix=extrinsic_data.get("rotation_matrix"),
        translation_vector=extrinsic_data.get("translation_vector"),
        camera_world_x=extrinsic_data.get("camera_world_x"),
        camera_world_y=extrinsic_data.get("camera_world_y"),
        camera_world_z=extrinsic_data.get("camera_world_z"),
        computed_at=now,
    )
    db.add(cal)

    cc.status = "calibrated"
    cc.updated_at = now

    await db.commit()
    await db.refresh(cal)

    # R5 (M5-S1): signal IEP2 to reload homography without pod restart
    try:
        await redis.publish(f"iep2:reload:{config_id}", "homography")
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Failed to publish homography reload signal  config_id=%s: %s", config_id, exc
        )

    return cal


@router.post(
    "/store/{slug}/draft/camera-configs/{config_id}/calibration/verify",
    response_model=CalibrationResponse,
)
async def verify_calibration(
    slug: str,
    config_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    cal_result = await db.execute(
        select(Calibration).where(
            Calibration.camera_config_id == config_id,
            Calibration.is_current == True,
        )
    )
    cal = cal_result.scalar_one_or_none()
    if not cal:
        raise HTTPException(status_code=404, detail={"error": "No current calibration", "code": "NO_CALIBRATION"})

    now = datetime.now(timezone.utc)
    cal.status = "verified"
    cal.verified_at = now
    cal.verified_by = ctx.user_id

    # Update camera config status
    await db.execute(
        update(CameraConfig)
        .where(CameraConfig.id == config_id)
        .values(status="verified", updated_at=now)
    )

    await db.commit()
    await db.refresh(cal)
    return cal


# ─── Sections ─────────────────────────────────────────────────────────────────

@router.post("/store/{slug}/sections", response_model=SectionResponse, status_code=201)
async def create_section(
    slug: str,
    body: CreateSectionRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    section = Section(
        store_id=ctx.store_id,
        name=body.name,
        type=body.type,
        display_order=body.display_order,
        is_default=False,
    )
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return section


@router.patch("/store/{slug}/sections/{section_id}", response_model=SectionResponse)
async def patch_section(
    slug: str,
    section_id: uuid.UUID,
    body: PatchSectionRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    result = await db.execute(
        select(Section).where(Section.id == section_id, Section.store_id == ctx.store_id)
    )
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail={"error": "Section not found", "code": "NOT_FOUND"})

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(section, field, value)
    section.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(section)
    return section


@router.delete("/store/{slug}/sections/{section_id}", status_code=204)
async def delete_section(
    slug: str,
    section_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    result = await db.execute(
        select(Section).where(
            Section.id == section_id,
            Section.store_id == ctx.store_id,
            Section.is_default == False,
        )
    )
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(
            status_code=404,
            detail={"error": "Section not found or is the default section", "code": "NOT_FOUND"},
        )
    section.status = "inactive"
    section.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ─── Activation ───────────────────────────────────────────────────────────────

@router.post("/store/{slug}/versions/draft/activate", response_model=VersionActivateResponse, status_code=202)
async def activate_draft(
    slug: str,
    body: VersionActivateRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    require_owner_or_manager(ctx)
    draft = await _require_draft(ctx.store_id, db)
    _require_draft_access(draft, ctx)

    # Pre-activation checklist: at least one section must have a floor plan uploaded.
    sections_result = await db.execute(
        select(Section).where(Section.store_id == ctx.store_id, Section.status == "active")
    )
    sections = sections_result.scalars().all()
    has_floor_plan = False
    for section in sections:
        fp_r = await db.execute(
            select(FloorPlan).where(
                FloorPlan.version_id == draft.id,
                FloorPlan.section_id == section.id,
                FloorPlan.image_uploaded == True,
            )
        )
        if fp_r.scalar_one_or_none():
            has_floor_plan = True
            break

    if not has_floor_plan:
        raise HTTPException(
            status_code=422,
            detail={"error": "At least one floor plan must be uploaded", "code": "NO_FLOOR_PLAN"},
        )

    # Checklist: at least one camera config must be verified.
    verified_result = await db.execute(
        select(CameraConfig).where(
            CameraConfig.version_id == draft.id,
            CameraConfig.status == "verified",
        )
    )
    if not verified_result.scalar_one_or_none():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "At least one camera must be calibrated and verified before activation",
                "code": "NO_VERIFIED_CAMERA",
            },
        )

    # Informational: query cameras currently running for this store (never blocks activation).
    from sqlalchemy import text as _text
    running_result = await db.execute(
        _text("""
            SELECT physical_camera_id
            FROM camera_runtime_sessions
            WHERE store_id = :store_id AND stopped_at IS NULL
        """),
        {"store_id": ctx.store_id},
    )
    cameras_pending = [row[0] for row in running_result.fetchall()]

    # Find the current active version (to archive it).
    active_result = await db.execute(
        select(StoreConfigVersion).where(
            StoreConfigVersion.store_id == ctx.store_id,
            StoreConfigVersion.status == "active",
        )
    )
    active_version = active_result.scalar_one_or_none()
    old_version_id = str(active_version.id) if active_version else None

    now = datetime.now(timezone.utc)

    if body.mode == "immediate":
        started_ids, stopped_ids = await orchestrator.activate_version_now(
            store_id=str(ctx.store_id),
            new_version_id=str(draft.id),
            old_version_id=old_version_id,
        )
        for cc_id in stopped_ids:
            mark_stopped(str(ctx.store_id), cc_id)
        for cc_id in started_ids:
            mark_running(str(ctx.store_id), cc_id)

        await write_audit_log(
            db, "version_activated",
            store_id=ctx.store_id, user_id=ctx.user_id,
            entity_type="store_config_version", entity_id=draft.id,
        )
        await db.commit()

        return VersionActivateResponse(
            version_id=draft.id,
            status="activating",
            activate_at=None,
            cameras_restarted=[uuid.UUID(cid) for cid in started_ids],
            cameras_pending=cameras_pending,
        )

    else:  # scheduled
        # Archive old active version and set draft to pending_activation atomically.
        if active_version:
            active_version.status = "archived"
            active_version.active_until = now
        draft.status = "pending_activation"
        draft.activate_at = body.activate_at
        await db.commit()

        return VersionActivateResponse(
            version_id=draft.id,
            status="scheduled",
            activate_at=body.activate_at,
            cameras_restarted=[],
            cameras_pending=cameras_pending,
        )


@router.get("/store/{slug}/versions/sync/{event_id}", response_model=SyncEventResponse)
async def poll_sync_event(
    slug: str,
    event_id: uuid.UUID,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    event_result = await db.execute(
        select(VersionSyncEvent).where(
            VersionSyncEvent.id == event_id,
            VersionSyncEvent.store_id == ctx.store_id,
        )
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail={"error": "Sync event not found", "code": "NOT_FOUND"})

    now = datetime.now(timezone.utc)

    # Execute activation when scheduled time has passed and still pending
    if event.status == "pending" and now >= event.scheduled_at:
        try:
            # Archive current active version
            await db.execute(
                update(StoreConfigVersion)
                .where(
                    StoreConfigVersion.store_id == ctx.store_id,
                    StoreConfigVersion.status == "active",
                )
                .values(status="archived", active_until=now)
            )
            # Activate draft
            await db.execute(
                update(StoreConfigVersion)
                .where(StoreConfigVersion.id == event.version_id)
                .values(status="active", active_from=now)
            )
            event.status = "executed"
            event.executed_at = now
            await write_audit_log(
                db, "version_activated",
                store_id=ctx.store_id, user_id=ctx.user_id,
                entity_type="store_config_version", entity_id=event.version_id,
            )
            await db.commit()
        except Exception as exc:
            event.status = "failed"
            event.error = str(exc)
            await db.commit()

    remaining = max(0.0, (event.scheduled_at - now).total_seconds()) if event.status == "pending" else None
    return SyncEventResponse(
        id=event.id,
        store_id=event.store_id,
        version_id=event.version_id,
        status=event.status,
        scheduled_at=event.scheduled_at,
        executed_at=event.executed_at,
        remaining_seconds=remaining,
    )


# ─── Draft Discard Request ────────────────────────────────────────────────────

@router.post("/store/{slug}/members/draft-discard-request", status_code=200)
async def request_draft_discard(
    slug: str,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    """Send an email to the draft owner requesting them to discard the draft."""
    from app.core.email import send_email

    draft = await _require_draft(ctx.store_id, db)
    if draft.created_by == ctx.user_id:
        raise HTTPException(status_code=400, detail={"error": "You own this draft", "code": "OWN_DRAFT"})

    from app.models.user import User
    owner_result = await db.execute(select(User).where(User.id == draft.created_by))
    owner = owner_result.scalar_one_or_none()
    if owner:
        try:
            await send_email(
                to=owner.email,
                subject="Draft discard request",
                body=(
                    f"A team member has requested that you discard your active store configuration draft "
                    f"for store '{slug}'. Please review and discard if appropriate."
                ),
            )
        except Exception:
            pass

    return {"message": "Request sent"}


