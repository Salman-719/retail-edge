"""Calibration-Files onboarding API (Method 2).

Endpoints for uploading OpenCV XML intrinsic/extrinsic calibration files per camera,
computing virtual world-map bounds from the camera geometry, and persisting the result.

No floor plan image is required — the 2D map canvas is derived automatically from
the camera calibration data.
"""
import logging

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import db as models
from app.schemas.camera import CalibrationFilesRequest, CalibrationResponse, ParsedCalibrationResponse
from app.schemas.store import FloorPlanResponse, WorldBoundsConfig
from app.utils.calibration_xml import (
    compute_camera_center,
    parse_extrinsic_xml,
    parse_intrinsic_xml,
    validate_calibration,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Helpers ───────────────────────────────────────────────────────────────────

_VIRTUAL_PPM = 100.0  # pixels-per-metre for the virtual canvas (display constant only)
_BOUNDS_PADDING = 0.10  # 10 % padding around auto-computed bounds


async def _get_camera_with_calibration(camera_id: str, store_id: str, db: AsyncSession) -> models.Camera:
    result = await db.execute(
        select(models.Camera)
        .where(models.Camera.id == camera_id)
        .options(selectinload(models.Camera.calibration))
    )
    cam = result.scalar_one_or_none()
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    return cam


async def _get_or_create_floor_plan(store_id: str, db: AsyncSession) -> models.FloorPlan:
    result = await db.execute(
        select(models.Store)
        .where(models.Store.id == store_id)
        .options(selectinload(models.Store.floor_plan))
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
    if store.floor_plan is None:
        fp = models.FloorPlan(store_id=store_id)
        db.add(fp)
        await db.flush()
        await db.refresh(fp)
        return fp
    return store.floor_plan


def _project_corner_to_ground(u: float, v: float, K_np: np.ndarray, R_np: np.ndarray, t_np: np.ndarray) -> tuple:
    """Project a single image corner pixel to the world ground plane (Z=0).

    Returns (world_x, world_y) or None if the ray doesn't hit the ground.
    """
    C = compute_camera_center(R_np, t_np)
    K_inv = np.linalg.inv(K_np)
    ray_cam = K_inv @ np.array([u, v, 1.0])
    ray_world = R_np.T @ ray_cam
    norm = np.linalg.norm(ray_world)
    if norm < 1e-10:
        return None
    d = ray_world / norm

    d_z = d[2]
    if abs(d_z) < 1e-4:
        return None  # ray parallel to ground
    s = (0.0 - C[2]) / d_z
    if s <= 0:
        return None  # intersection behind camera
    pt = C + s * d
    return (float(pt[0]), float(pt[1]))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{store_id}/calibration-files/parse",
    response_model=ParsedCalibrationResponse,
    summary="Parse intrinsic + extrinsic XML files (no DB write)",
)
async def parse_calibration_files(
    store_id: str,
    intr_file: UploadFile = File(..., description="Intrinsic XML file (intr_*.xml)"),
    extr_file: UploadFile = File(..., description="Extrinsic XML file (extr_*.xml)"),
    scale_factor: float = Form(1.0, description="Multiply tvec by this value (e.g. 0.001 to convert mm → m)"),
):
    """Parse OpenCV XML calibration files server-side and return the parsed data + warnings.

    No data is written to the database. Call POST `/{store_id}/cameras/{camera_id}/calibration-files`
    to persist after the user has confirmed the parsed values.
    """
    intr_bytes = await intr_file.read()
    extr_bytes = await extr_file.read()

    try:
        intr_data = parse_intrinsic_xml(intr_bytes)
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse intrinsic file: {exc}")

    try:
        extr_data = parse_extrinsic_xml(extr_bytes, scale_factor=scale_factor)
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse extrinsic file: {exc}")

    K = intr_data["intrinsic_matrix"]
    dist_coeffs = intr_data["dist_coeffs"]
    R = extr_data["rotation_matrix"]
    t = extr_data["translation_vector"]

    issues = validate_calibration(K, dist_coeffs, R, t)

    # Block on errors; surface warnings
    errors = [i for i in issues if i["level"] == "error"]
    if errors:
        raise HTTPException(422, "; ".join(e["message"] for e in errors))

    warnings = [i["message"] for i in issues if i["level"] == "warning"]

    R_np = np.array(R, dtype=np.float64)
    t_np = np.array(t, dtype=np.float64)
    C = compute_camera_center(R_np, t_np)

    return ParsedCalibrationResponse(
        intrinsic_matrix=K,
        dist_coeffs=dist_coeffs,
        rotation_matrix=R,
        translation_vector=t,
        image_width=1920,   # default; user can override in CalibrationFilesRequest
        image_height=1080,
        camera_world_xyz=C.tolist(),
        warnings=warnings,
    )


@router.post(
    "/{store_id}/cameras/{camera_id}/calibration-files",
    response_model=CalibrationResponse,
    summary="Save parsed calibration data to DB (Method 2)",
)
async def save_calibration_files(
    store_id: str,
    camera_id: str,
    payload: CalibrationFilesRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist intrinsic/extrinsic calibration data for a camera (Method 2).

    Sets calibration.method = 'calibration_files' and calibration.status = 'ok'.
    """
    cam = await _get_camera_with_calibration(camera_id, store_id, db)

    R_np = np.array(payload.rotation_matrix, dtype=np.float64)
    t_np = np.array(payload.translation_vector, dtype=np.float64)
    C = compute_camera_center(R_np, t_np)

    if cam.calibration is None:
        cal = models.Calibration(camera_id=camera_id)
        db.add(cal)
    else:
        cal = cam.calibration

    cal.method = "calibration_files"
    cal.intrinsic_matrix = payload.intrinsic_matrix
    cal.dist_coeffs = payload.dist_coeffs
    cal.rotation_matrix = payload.rotation_matrix
    cal.translation_vector = payload.translation_vector
    cal.image_width = payload.image_width
    cal.image_height = payload.image_height
    cal.camera_world_x = float(C[0])
    cal.camera_world_y = float(C[1])
    cal.camera_world_z = float(C[2])
    cal.status = "ok"
    # Clear homography fields (not applicable for this method)
    cal.correspondences = None
    cal.homography_matrix = None
    cal.reprojection_error = None

    await db.flush()
    await db.refresh(cal)
    return cal


@router.get(
    "/{store_id}/calibration-files/world-bounds-from-cameras",
    response_model=WorldBoundsConfig,
    summary="Auto-compute world bounds from all calibrated cameras (Method 2)",
)
async def get_world_bounds_from_cameras(store_id: str, db: AsyncSession = Depends(get_db)):
    """Project image-corner pixels from each calibrated camera to the ground plane and
    return the bounding box of all resulting world points (+ 10 % padding).
    """
    result = await db.execute(
        select(models.Camera)
        .where(models.Camera.store_id == store_id)
        .options(selectinload(models.Camera.calibration))
    )
    cameras = result.scalars().all()

    cal_cameras = [c for c in cameras if c.calibration and c.calibration.method == "calibration_files"]
    if not cal_cameras:
        raise HTTPException(422, "No cameras with calibration_files method found for this store")

    all_x: list = []
    all_y: list = []

    for cam in cal_cameras:
        cal = cam.calibration
        K_np = np.array(cal.intrinsic_matrix, dtype=np.float64)
        R_np = np.array(cal.rotation_matrix, dtype=np.float64)
        t_np = np.array(cal.translation_vector, dtype=np.float64)

        W = float(cal.image_width or 1920)
        H = float(cal.image_height or 1080)

        # Project the 4 image corners to the ground plane
        for (u, v) in [(0, 0), (W, 0), (0, H), (W, H)]:
            pt = _project_corner_to_ground(u, v, K_np, R_np, t_np)
            if pt is not None:
                all_x.append(pt[0])
                all_y.append(pt[1])

        # Also include the camera position itself
        all_x.append(float(cal.camera_world_x))
        all_y.append(float(cal.camera_world_y))

    if not all_x:
        raise HTTPException(422, "Could not project any image corners to the ground plane — check calibration data")

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)

    x_range = max(x_max - x_min, 1.0)
    y_range = max(y_max - y_min, 1.0)
    pad_x = x_range * _BOUNDS_PADDING
    pad_y = y_range * _BOUNDS_PADDING

    return WorldBoundsConfig(
        world_x_min=x_min - pad_x,
        world_x_max=x_max + pad_x,
        world_y_min=y_min - pad_y,
        world_y_max=y_max + pad_y,
    )


@router.put(
    "/{store_id}/floor-plan/world-bounds",
    response_model=FloorPlanResponse,
    summary="Set virtual canvas world bounds for Method 2 stores",
)
async def save_world_bounds(
    store_id: str,
    payload: WorldBoundsConfig,
    db: AsyncSession = Depends(get_db),
):
    """Upsert the FloorPlan row with world bounds (no image required for Method 2).

    Sets pixels_per_meter=100 as a display rendering constant and origin_x/y=0.
    """
    fp = await _get_or_create_floor_plan(store_id, db)

    fp.world_x_min = payload.world_x_min
    fp.world_x_max = payload.world_x_max
    fp.world_y_min = payload.world_y_min
    fp.world_y_max = payload.world_y_max

    # Virtual canvas rendering constants (no physical image)
    fp.pixels_per_meter = _VIRTUAL_PPM
    fp.origin_x = 0.0
    fp.origin_y = 0.0

    world_w = max(payload.world_x_max - payload.world_x_min, 0.1)
    world_h = max(payload.world_y_max - payload.world_y_min, 0.1)
    fp.width_px = int(world_w * _VIRTUAL_PPM)
    fp.height_px = int(world_h * _VIRTUAL_PPM)

    await db.flush()
    await db.refresh(fp)
    return fp
