"""Video proxy — EEP validates the request then delegates to IEP1-ingestion.

EEP is responsible for:
  - Verifying the camera exists and belongs to the store
  - Forwarding the upload/frame request to IEP1

IEP1 is responsible for:
  - Writing the video to S3
  - Extracting metadata (fps, duration, dimensions) with OpenCV
  - Updating the camera row in the DB
  - Serving frame extractions
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models import db as models

logger = logging.getLogger(__name__)
router = APIRouter()


def _iep1_url(path: str) -> str:
    return f"{settings.IEP1_URL}/ingest/{path}"


@router.post("/{store_id}/cameras/{camera_id}/video")
async def upload_video(
    store_id: str,
    camera_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")

    raw = await file.read()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            _iep1_url(f"{store_id}/cameras/{camera_id}/video"),
            files={"file": (file.filename, raw, file.content_type or "video/mp4")},
        )
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)

    # Refresh camera from DB so response has up-to-date video metadata
    await db.refresh(cam)
    return cam


@router.get("/{store_id}/cameras/{camera_id}/frame")
async def get_frame(
    store_id: str,
    camera_id: str,
    timestamp_sec: float = Query(0.0),
    db: AsyncSession = Depends(get_db),
):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _iep1_url(f"{store_id}/cameras/{camera_id}/frame"),
            params={"timestamp_sec": timestamp_sec},
        )
    if resp.status_code == 404:
        raise HTTPException(404, "Video not found")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)

    return Response(content=resp.content, media_type="image/jpeg")
