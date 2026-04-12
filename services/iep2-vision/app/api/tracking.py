"""IEP2 tracking endpoints.

EEP calls these after validating permissions and fetching camera/calibration data.
Job state is persisted in Redis. Frame buffer is in-process (MJPEG only).
"""
import json
import os
import time
import threading
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, Response

from app.core.config import settings
from app.core.s3_client import s3_client
from app.core.redis_client import async_redis, job_key
from app.core.metrics import heatmap_generation_duration
from app.schemas import (
    TrackingStartRequest, TrackingStartResponse,
    TrackingProgressResponse, TrajectoryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# In-process frame buffer per camera (for MJPEG stream only)
_frame_buffers: dict[str, list] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_job(camera_id: str) -> dict:
    data = await async_redis.hgetall(job_key(camera_id))
    if not data:
        raise HTTPException(404, "No tracking job found for this camera")
    # Deserialise JSON fields
    for field in ("zone_occupancy", "trajectory", "zones", "origin_px"):
        if field in data:
            try:
                data[field] = json.loads(data[field])
            except (json.JSONDecodeError, TypeError):
                data[field] = {} if field in ("zone_occupancy", "origin_px") else []
    for field in ("progress", "total_frames"):
        if field in data:
            try:
                data[field] = int(data[field])
            except (ValueError, TypeError):
                data[field] = 0
    return data


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{store_id}/cameras/{camera_id}/tracking/start", response_model=TrackingStartResponse)
async def start_tracking(
    store_id: str,
    camera_id: str,
    payload: TrackingStartRequest,
    model_size: str = Query("yolov8n"),
):
    from app.utils.tracker import run_tracking_job

    # Check if already running
    if await async_redis.exists(job_key(camera_id)):
        job = await _get_job(camera_id)
        if job.get("status") == "running":
            return {"status": "already_running"}

    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)

    ext = Path(payload.video_s3_key).suffix
    video_path = os.path.join(tmp_dir, f"track_{camera_id}{ext}")
    s3_client.download_to_file(payload.video_s3_key, video_path)

    floor_plan_path = None
    if payload.floor_plan_s3_key:
        fp_ext = Path(payload.floor_plan_s3_key).suffix
        floor_plan_path = os.path.join(tmp_dir, f"fp_{store_id}{fp_ext}")
        s3_client.download_to_file(payload.floor_plan_s3_key, floor_plan_path)

    frame_buffer = []
    _frame_buffers[camera_id] = frame_buffer

    # Persist job metadata to Redis so _persist_results can use it
    from app.core.redis_client import sync_redis
    sync_redis.update_job(camera_id,
        zones=payload.zones,
        pixels_per_meter=payload.pixels_per_meter,
        origin_px=payload.origin_px or {"x": 0, "y": 0},
        projection_method=payload.projection_method,
        world_bounds=json.dumps(payload.world_bounds) if payload.world_bounds else "{}",
    )

    thread = threading.Thread(
        target=run_tracking_job,
        args=(
            frame_buffer,
            camera_id,
            store_id,
            video_path,
            payload.homography_matrix,
            payload.zones,
            payload.pixels_per_meter,
            payload.model_size,
            payload.projection_method,
            payload.intrinsic_matrix,
            payload.dist_coeffs,
            payload.rotation_matrix,
            payload.translation_vector,
        ),
        daemon=True,
    )
    thread.start()
    return {"status": "started"}


@router.get("/{store_id}/cameras/{camera_id}/tracking/stream")
async def stream_tracking(store_id: str, camera_id: str):
    """MJPEG stream of annotated tracking frames."""
    if camera_id not in _frame_buffers:
        raise HTTPException(404, "No tracking job found")

    def generate():
        buf = _frame_buffers[camera_id]
        while True:
            if buf:
                frame_bytes = buf.pop(0)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            else:
                time.sleep(0.04)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/{store_id}/cameras/{camera_id}/tracking/progress", response_model=TrackingProgressResponse)
async def tracking_progress(store_id: str, camera_id: str):
    job = await _get_job(camera_id)

    # When done, persist results to S3 + DB.
    # Also retry if previously persisted but heatmap is missing.
    if job.get("status") == "done":
        if not job.get("_persisted"):
            await _persist_results(job)
        elif not job.get("heatmap_s3_key"):
            # Previous attempt ran but heatmap failed — clear flag and retry
            from app.core.redis_client import sync_redis as _sync
            _sync.update_job(job["camera_id"], _persisted="0")
            job["_persisted"] = "0"
            await _persist_results(job)

    return {
        "status": job.get("status", "idle"),
        "progress": job.get("progress", 0),
        "total_frames": job.get("total_frames", 0),
        "zone_occupancy": job.get("zone_occupancy", {}),
        "error": job.get("error") or None,
        "heatmap_url": (
            f"/tracking/{store_id}/cameras/{camera_id}/tracking/heatmap"
            if job.get("status") == "done" else None
        ),
    }


@router.get("/{store_id}/cameras/{camera_id}/tracking/heatmap")
async def get_heatmap(store_id: str, camera_id: str):
    job = await _get_job(camera_id)
    heatmap_key = job.get("heatmap_s3_key", "")
    if not heatmap_key:
        raise HTTPException(404, "Heatmap not yet available")
    img_bytes = s3_client.download_bytes(heatmap_key)
    return Response(content=img_bytes, media_type="image/png")


@router.get("/{store_id}/cameras/{camera_id}/tracking/trajectory", response_model=TrajectoryResponse)
async def get_trajectory(store_id: str, camera_id: str):
    job = await _get_job(camera_id)
    return TrajectoryResponse(trajectory=job.get("trajectory", []))


# ── Result persistence ────────────────────────────────────────────────────────

async def _persist_results(job: dict):
    """Generate heatmap, upload to S3, save TrackingResult row to DB."""
    import uuid
    import sqlalchemy as sa
    from app.utils.heatmap import generate_heatmap_bytes
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import sync_redis

    camera_id = job["camera_id"]
    store_id = job["store_id"]

    # ── Heatmap ──────────────────────────────────────────────────────────────
    # Find floor plan file regardless of extension (.png, .jpg, etc.)
    import glob as _glob
    fp_matches = _glob.glob(os.path.join(settings.TMP_DIR, f"fp_{store_id}.*"))
    floor_plan_path = fp_matches[0] if fp_matches else None
    heatmap_s3_key = None

    if floor_plan_path and os.path.exists(floor_plan_path):
        try:
            origin_px = job.get("origin_px") or {"x": 0, "y": 0}
            if isinstance(origin_px, str):
                import json as _json
                origin_px = _json.loads(origin_px)
            with heatmap_generation_duration.time():
                heatmap_bytes = generate_heatmap_bytes(
                    floor_plan_path,
                    job.get("trajectory", []),
                    job.get("zones", []),
                    job.get("zone_occupancy", {}),
                    float(job.get("pixels_per_meter", 100.0)),
                    origin_px=origin_px,
                )
            heatmap_s3_key = f"stores/{store_id}/cameras/{camera_id}/heatmap.png"
            s3_client.upload_bytes(heatmap_s3_key, heatmap_bytes, "image/png")
        except Exception:
            logger.exception("Heatmap generation failed")
    else:
        # Method 2: no floor plan image — generate a virtual canvas heatmap from world bounds
        wb_str = job.get("world_bounds", "{}")
        try:
            wb = json.loads(wb_str) if isinstance(wb_str, str) else (wb_str or {})
        except (json.JSONDecodeError, TypeError):
            wb = {}
        if wb.get("x_min") is not None:
            try:
                from app.utils.heatmap import generate_virtual_heatmap_bytes
                with heatmap_generation_duration.time():
                    heatmap_bytes = generate_virtual_heatmap_bytes(
                        job.get("trajectory", []),
                        job.get("zones", []),
                        job.get("zone_occupancy", {}),
                        wb,
                    )
                heatmap_s3_key = f"stores/{store_id}/cameras/{camera_id}/heatmap.png"
                s3_client.upload_bytes(heatmap_s3_key, heatmap_bytes, "image/png")
            except Exception:
                logger.exception("Virtual heatmap generation failed")

    # ── DB persist ───────────────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO tracking_results "
                    "(id, store_id, camera_id, trajectory_data, zone_occupancy, heatmap_s3_key, created_at) "
                    "VALUES (:id, :store_id, :camera_id, CAST(:traj AS jsonb), CAST(:occ AS jsonb), :hm, now())"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "store_id": store_id,
                    "camera_id": camera_id,
                    "traj": json.dumps(job.get("trajectory", [])),
                    "occ": json.dumps(job.get("zone_occupancy", {})),
                    "hm": heatmap_s3_key,
                },
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to persist tracking result to DB")

    # Mark persisted in Redis
    sync_redis.update_job(camera_id, _persisted="1", heatmap_s3_key=heatmap_s3_key or "")
