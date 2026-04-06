import io
import os
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.s3_client import s3_client
from app.core.config import settings
from app.models import db as models
from app.models.schemas import FloorPlanResponse, ScaleConfig
from app.utils.pdf_utils import pdf_to_png_bytes

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_or_create_floor_plan(store_id: str, db: AsyncSession) -> models.FloorPlan:
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
    if store.floor_plan is None:
        fp = models.FloorPlan(store_id=store_id)
        db.add(fp)
        await db.flush()
        await db.refresh(fp)
        return fp
    return store.floor_plan


@router.post("/{store_id}/floor-plan/upload", response_model=FloorPlanResponse)
async def upload_floor_plan(
    store_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    raw = await file.read()
    filename = file.filename or "floorplan"

    # Convert PDF to PNG if needed
    if filename.lower().endswith(".pdf"):
        img_bytes = pdf_to_png_bytes(raw)
        content_type = "image/png"
        ext = "png"
    else:
        img_bytes = raw
        content_type = file.content_type or "image/png"
        ext = Path(filename).suffix.lstrip(".") or "png"

    # Get image dimensions
    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes))
    width_px, height_px = img.size

    # Upload to S3
    s3_key = f"stores/{store_id}/floor_plan/floorplan.{ext}"
    s3_client.upload_bytes(s3_key, img_bytes, content_type)

    # Upsert floor plan record
    fp = await _get_or_create_floor_plan(store_id, db)
    fp.s3_key = s3_key
    fp.width_px = width_px
    fp.height_px = height_px
    await db.flush()
    await db.refresh(fp)
    return fp


@router.get("/{store_id}/floor-plan", response_model=FloorPlanResponse)
async def get_floor_plan(store_id: str, db: AsyncSession = Depends(get_db)):
    fp = await _get_or_create_floor_plan(store_id, db)
    return fp


@router.get("/{store_id}/floor-plan/image")
async def get_floor_plan_image(store_id: str, db: AsyncSession = Depends(get_db)):
    """Proxy floor plan image from S3 so the frontend doesn't need direct MinIO access."""
    store = await db.get(models.Store, store_id)
    if not store or not store.floor_plan or not store.floor_plan.s3_key:
        raise HTTPException(404, "Floor plan image not found")

    key = store.floor_plan.s3_key
    try:
        img_bytes = s3_client.download_bytes(key)
    except Exception:
        raise HTTPException(404, "Image not found in storage")

    media_type = "image/png" if key.endswith(".png") else "image/jpeg"
    return Response(content=img_bytes, media_type=media_type)


@router.put("/{store_id}/floor-plan/scale", response_model=FloorPlanResponse)
async def save_scale(store_id: str, payload: ScaleConfig, db: AsyncSession = Depends(get_db)):
    fp = await _get_or_create_floor_plan(store_id, db)
    if payload.origin_px is not None:
        fp.origin_x = payload.origin_px.x
        fp.origin_y = payload.origin_px.y
    if payload.scale_point1_px is not None:
        fp.scale_point1_x = payload.scale_point1_px.x
        fp.scale_point1_y = payload.scale_point1_px.y
    if payload.scale_point2_px is not None:
        fp.scale_point2_x = payload.scale_point2_px.x
        fp.scale_point2_y = payload.scale_point2_px.y
    if payload.real_world_distance_m is not None:
        fp.real_world_distance_m = payload.real_world_distance_m
    if payload.pixels_per_meter is not None:
        fp.pixels_per_meter = payload.pixels_per_meter
    await db.flush()
    await db.refresh(fp)
    return fp
