"""Tracking proxy — EEP validates the request then delegates to IEP2-vision.

EEP is responsible for:
  - Verifying camera exists and belongs to store
  - Verifying camera has a video and a valid calibration
  - Fetching camera/floor-plan/zone data from DB
  - Forwarding to IEP2 with a fully-resolved payload

IEP2 is responsible for:
  - Running YOLO+ByteTrack
  - Managing job state in Redis
  - Serving the MJPEG stream, progress, heatmap, and trajectory
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.config import settings
from app.models import db as models

logger = logging.getLogger(__name__)
router = APIRouter()


def _iep2_url(path: str) -> str:
    return f"{settings.IEP2_URL}/tracking/{path}"


# ── Start ─────────────────────────────────────────────────────────────────────

@router.post("/{store_id}/cameras/{camera_id}/tracking/start")
async def start_tracking(
    store_id: str,
    camera_id: str,
    model_size: str = Query("yolov8n"),
    db: AsyncSession = Depends(get_db),
):
    cam_result = await db.execute(
        select(models.Camera)
        .where(models.Camera.id == camera_id)
        .options(selectinload(models.Camera.calibration))
    )
    cam = cam_result.scalar_one_or_none()
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    if not cam.video_s3_key:
        raise HTTPException(400, "No video uploaded for this camera")
    if not cam.calibration or cam.calibration.status != "ok":
        raise HTTPException(400, "Camera is not calibrated")

    store_result = await db.execute(
        select(models.Store)
        .where(models.Store.id == store_id)
        .options(
            selectinload(models.Store.floor_plan),
            selectinload(models.Store.zones),
        )
    )
    store = store_result.scalar_one_or_none()
    fp = store.floor_plan if store else None
    zones_data = [
        {"id": z.id, "name": z.name, "type": z.type, "points": z.points}
        for z in (store.zones if store else [])
    ]

    payload = {
        "video_s3_key": cam.video_s3_key,
        "floor_plan_s3_key": fp.s3_key if fp else None,
        "homography_matrix": cam.calibration.homography_matrix,
        "zones": zones_data,
        "pixels_per_meter": fp.pixels_per_meter if fp else 100.0,
        "origin_px": {"x": fp.origin_x or 0, "y": fp.origin_y or 0} if fp else {"x": 0, "y": 0},
        "model_size": model_size,
        "store_id": store_id,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _iep2_url(f"{store_id}/cameras/{camera_id}/tracking/start"),
            json=payload,
            params={"model_size": model_size},
        )
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


# ── Stream ────────────────────────────────────────────────────────────────────

@router.get("/{store_id}/cameras/{camera_id}/tracking/stream")
async def stream_tracking(store_id: str, camera_id: str):
    """Proxy MJPEG stream from IEP2."""
    url = _iep2_url(f"{store_id}/cameras/{camera_id}/tracking/stream")

    async def generate():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield chunk

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── Progress ──────────────────────────────────────────────────────────────────

@router.get("/{store_id}/cameras/{camera_id}/tracking/progress")
async def tracking_progress(store_id: str, camera_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_iep2_url(f"{store_id}/cameras/{camera_id}/tracking/progress"))
    if resp.status_code == 404:
        return {"status": "idle"}
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


# ── Heatmap ───────────────────────────────────────────────────────────────────

@router.get("/{store_id}/cameras/{camera_id}/tracking/heatmap")
async def get_heatmap(store_id: str, camera_id: str):
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_iep2_url(f"{store_id}/cameras/{camera_id}/tracking/heatmap"))
    if resp.status_code == 404:
        raise HTTPException(404, "No heatmap available")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return Response(content=resp.content, media_type="image/png")


# ── Trajectory ────────────────────────────────────────────────────────────────

@router.get("/{store_id}/cameras/{camera_id}/tracking/trajectory")
async def get_trajectory(store_id: str, camera_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_iep2_url(f"{store_id}/cameras/{camera_id}/tracking/trajectory"))
    if resp.status_code == 404:
        return {"trajectory": []}
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()
