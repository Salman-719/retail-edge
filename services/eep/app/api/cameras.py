import io
import os
import uuid
import logging
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.s3_client import s3_client
from app.core.config import settings
from app.models import db as models
from app.models.schemas import CameraCreate, CameraUpdate, CameraResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{store_id}/cameras", response_model=list[CameraResponse])
async def list_cameras(store_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Camera).where(models.Camera.store_id == store_id)
    )
    cameras = result.scalars().all()
    # Eagerly load calibrations
    for cam in cameras:
        _ = cam.calibration
    return cameras


@router.post("/{store_id}/cameras", response_model=CameraResponse, status_code=201)
async def create_camera(store_id: str, payload: CameraCreate, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
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
    await db.refresh(cam)
    return cam


@router.put("/{store_id}/cameras/{camera_id}", response_model=CameraResponse)
async def update_camera(
    store_id: str, camera_id: str, payload: CameraUpdate, db: AsyncSession = Depends(get_db)
):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    for field, val in payload.model_dump(exclude_none=True).items():
        setattr(cam, field, val)
    await db.flush()
    await db.refresh(cam)
    return cam


@router.delete("/{store_id}/cameras/{camera_id}", status_code=204)
async def delete_camera(store_id: str, camera_id: str, db: AsyncSession = Depends(get_db)):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    await db.delete(cam)


@router.post("/{store_id}/cameras/{camera_id}/video", response_model=CameraResponse)
async def upload_video(
    store_id: str,
    camera_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")

    # Write to temp file to extract metadata with OpenCV
    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = Path(file.filename or "video.mp4").suffix
    tmp_path = os.path.join(tmp_dir, f"{camera_id}{ext}")

    raw = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(raw)

    cap = cv2.VideoCapture(tmp_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps else 0
    cap.release()

    # Upload to S3
    s3_key = f"stores/{store_id}/cameras/{camera_id}/video{ext}"
    s3_client.upload_file(s3_key, tmp_path, content_type="video/mp4")
    os.remove(tmp_path)

    cam.video_s3_key = s3_key
    cam.video_fps = fps
    cam.video_duration = duration
    cam.video_width = width
    cam.video_height = height
    await db.flush()
    await db.refresh(cam)
    return cam


@router.get("/{store_id}/cameras/{camera_id}/frame")
async def get_frame(
    store_id: str,
    camera_id: str,
    timestamp_sec: float = Query(0.0),
    db: AsyncSession = Depends(get_db),
):
    """Extract and return a JPEG frame at the given timestamp from the stored video."""
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id or not cam.video_s3_key:
        raise HTTPException(404, "Video not found")

    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = Path(cam.video_s3_key).suffix
    tmp_path = os.path.join(tmp_dir, f"frame_{camera_id}{ext}")

    try:
        s3_client.download_to_file(cam.video_s3_key, tmp_path)
        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        target_frame = int(timestamp_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            raise HTTPException(400, "Could not read frame at given timestamp")

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
