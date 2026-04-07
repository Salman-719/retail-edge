"""Camera CRUD routes.

Video upload and frame extraction live in api/videos.py.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import db as models
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse

logger = logging.getLogger(__name__)
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


@router.get("/{store_id}/cameras", response_model=list[CameraResponse])
async def list_cameras(store_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Camera)
        .where(models.Camera.store_id == store_id)
        .options(selectinload(models.Camera.calibration))
    )
    return result.scalars().all()


@router.post("/{store_id}/cameras", response_model=CameraResponse, status_code=201)
async def create_camera(store_id: str, payload: CameraCreate, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
    # Upsert: if camera with this ID already exists for this store, update it
    if payload.id:
        result = await db.execute(
            select(models.Camera)
            .where(models.Camera.id == payload.id)
            .options(selectinload(models.Camera.calibration))
        )
        existing = result.scalar_one_or_none()
        if existing and existing.store_id == store_id:
            if payload.name is not None:
                existing.name = payload.name
            if payload.position_x is not None:
                existing.position_x = payload.position_x
            if payload.position_y is not None:
                existing.position_y = payload.position_y
            if payload.height_meters is not None:
                existing.height_meters = payload.height_meters
            if payload.rtsp_url is not None:
                existing.rtsp_url = payload.rtsp_url
            await db.flush()
            return await _get_camera_with_calibration(existing.id, store_id, db)
    cam = models.Camera(
        id=payload.id,
        store_id=store_id,
        name=payload.name,
        position_x=payload.position_x,
        position_y=payload.position_y,
        height_meters=payload.height_meters,
        rtsp_url=payload.rtsp_url,
    )
    db.add(cam)
    await db.flush()
    # Re-fetch with calibration loaded (will be None for a new camera, but must be present for schema)
    return await _get_camera_with_calibration(cam.id, store_id, db)


@router.put("/{store_id}/cameras/{camera_id}", response_model=CameraResponse)
async def update_camera(
    store_id: str, camera_id: str, payload: CameraUpdate, db: AsyncSession = Depends(get_db)
):
    cam = await _get_camera_with_calibration(camera_id, store_id, db)
    for field, val in payload.model_dump(exclude_none=True).items():
        setattr(cam, field, val)
    await db.flush()
    return await _get_camera_with_calibration(camera_id, store_id, db)


@router.delete("/{store_id}/cameras/{camera_id}", status_code=204)
async def delete_camera(store_id: str, camera_id: str, db: AsyncSession = Depends(get_db)):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    await db.delete(cam)
