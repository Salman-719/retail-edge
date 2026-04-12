from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import db as models
from app.schemas.camera import CalibrationRequest, CalibrationResponse
from app.utils.homography import compute_homography
from app.core.metrics import calibration_attempts

router = APIRouter()


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


@router.post("/{store_id}/cameras/{camera_id}/calibrate", response_model=CalibrationResponse)
async def calibrate_camera(
    store_id: str,
    camera_id: str,
    payload: CalibrationRequest,
    db: AsyncSession = Depends(get_db),
):
    cam = await _get_camera_with_calibration(camera_id, store_id, db)

    correspondences = [
        {"camPx": c.camPx.model_dump(), "floorM": c.floorM.model_dump()}
        for c in payload.correspondences
    ]

    result = compute_homography(correspondences)
    status = result.get("status", "failed")
    calibration_attempts.labels(status=status).inc()

    if cam.calibration is None:
        cal = models.Calibration(camera_id=camera_id)
        db.add(cal)
    else:
        cal = cam.calibration

    cal.correspondences = correspondences
    cal.homography_matrix = result.get("homography_matrix")
    cal.reprojection_error = result.get("mean_error")
    cal.status = status

    await db.flush()
    await db.refresh(cal)
    return cal


@router.get("/{store_id}/cameras/{camera_id}/calibration", response_model=CalibrationResponse)
async def get_calibration(store_id: str, camera_id: str, db: AsyncSession = Depends(get_db)):
    cam = await _get_camera_with_calibration(camera_id, store_id, db)
    if not cam.calibration:
        raise HTTPException(404, "No calibration found for this camera")
    return cam.calibration
