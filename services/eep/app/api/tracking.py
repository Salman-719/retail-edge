"""
Tracking test mode — kept in EEP for Milestone 2 store-onboarding testing.
Will be refactored into IEP2-vision in Milestone 3.
"""
import io
import os
import json
import time
import threading
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.s3_client import s3_client
from app.core.config import settings
from app.models import db as models

logger = logging.getLogger(__name__)
router = APIRouter()

# In-process job state (per camera). For production this moves to Redis.
_jobs: dict[str, dict] = {}


@router.post("/{store_id}/cameras/{camera_id}/tracking/start")
async def start_tracking(
    store_id: str,
    camera_id: str,
    model_size: str = Query("yolov8n", description="yolov8n|yolov8s|yolov8m"),
    db: AsyncSession = Depends(get_db),
):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")
    if not cam.video_s3_key:
        raise HTTPException(400, "No video uploaded for this camera")
    if not cam.calibration or cam.calibration.status != "ok":
        raise HTTPException(400, "Camera is not calibrated")

    if camera_id in _jobs and _jobs[camera_id].get("status") == "running":
        return {"status": "already_running"}

    # Load dependencies lazily to avoid slow import at startup
    from app.utils.tracker import run_tracking_job

    # Download video to temp
    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = Path(cam.video_s3_key).suffix
    video_path = os.path.join(tmp_dir, f"track_{camera_id}{ext}")
    s3_client.download_to_file(cam.video_s3_key, video_path)

    # Download floor plan
    fp = cam.store.floor_plan if cam.store else None
    floor_plan_path = None
    if fp and fp.s3_key:
        fp_ext = Path(fp.s3_key).suffix
        floor_plan_path = os.path.join(tmp_dir, f"fp_{store_id}{fp_ext}")
        s3_client.download_to_file(fp.s3_key, floor_plan_path)

    # Build zones dict
    zones_data = []
    store = await db.get(models.Store, store_id)
    if store:
        zones_data = [
            {"id": z.id, "name": z.name, "type": z.type, "points": z.points}
            for z in store.zones
        ]

    homography = cam.calibration.homography_matrix
    pixels_per_meter = fp.pixels_per_meter if fp else 100.0

    job = {
        "status": "running",
        "progress": 0,
        "total_frames": 0,
        "zone_occupancy": {},
        "trajectory": [],
        "frames": [],
        "error": None,
        "store_id": store_id,
        "camera_id": camera_id,
        "floor_plan_path": floor_plan_path,
    }
    _jobs[camera_id] = job

    thread = threading.Thread(
        target=run_tracking_job,
        args=(job, video_path, homography, zones_data, pixels_per_meter, model_size),
        daemon=True,
    )
    thread.start()
    return {"status": "started"}


@router.get("/{store_id}/cameras/{camera_id}/tracking/stream")
async def stream_tracking(store_id: str, camera_id: str):
    """MJPEG stream of annotated tracking frames."""
    if camera_id not in _jobs:
        raise HTTPException(404, "No tracking job found")

    def generate():
        job = _jobs[camera_id]
        while True:
            if job["frames"]:
                frame_bytes = job["frames"].pop(0)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            elif job["status"] in ("done", "error"):
                break
            else:
                time.sleep(0.04)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/{store_id}/cameras/{camera_id}/tracking/progress")
async def tracking_progress(
    store_id: str,
    camera_id: str,
    db: AsyncSession = Depends(get_db),
):
    if camera_id not in _jobs:
        return {"status": "idle"}

    job = _jobs[camera_id]

    # When done, persist results to DB and S3
    if job["status"] == "done" and not job.get("_persisted"):
        job["_persisted"] = True
        await _persist_results(job, db)

    return {
        "status": job["status"],
        "progress": job["progress"],
        "total_frames": job["total_frames"],
        "zone_occupancy": job["zone_occupancy"],
        "error": job["error"],
        "heatmap_url": f"/api/stores/{job['store_id']}/cameras/{job['camera_id']}/tracking/heatmap"
        if job["status"] == "done"
        else None,
    }


@router.get("/{store_id}/cameras/{camera_id}/tracking/heatmap")
async def get_heatmap(store_id: str, camera_id: str, db: AsyncSession = Depends(get_db)):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")

    # Look for latest tracking result
    result = next(
        (r for r in reversed(cam.tracking_results) if r.heatmap_s3_key), None
    )
    if not result:
        raise HTTPException(404, "No heatmap available")

    img_bytes = s3_client.download_bytes(result.heatmap_s3_key)
    return Response(content=img_bytes, media_type="image/png")


async def _persist_results(job: dict, db: AsyncSession):
    camera_id = job["camera_id"]
    store_id = job["store_id"]

    # Generate heatmap
    heatmap_s3_key = None
    floor_plan_path = job.get("floor_plan_path")
    if floor_plan_path and os.path.exists(floor_plan_path):
        from app.utils.heatmap import generate_heatmap_bytes

        store = await db.get(models.Store, store_id)
        zones_data = []
        pixels_per_meter = 100.0
        if store and store.floor_plan:
            pixels_per_meter = store.floor_plan.pixels_per_meter or 100.0
            zones_data = [
                {"id": z.id, "name": z.name, "type": z.type, "points": z.points}
                for z in store.zones
            ]

        heatmap_bytes = generate_heatmap_bytes(
            floor_plan_path,
            job["trajectory"],
            zones_data,
            job["zone_occupancy"],
            pixels_per_meter,
        )
        heatmap_s3_key = f"stores/{store_id}/cameras/{camera_id}/heatmap.png"
        s3_client.upload_bytes(heatmap_s3_key, heatmap_bytes, "image/png")

    # Save tracking result to DB
    cam = await db.get(models.Camera, camera_id)
    if cam:
        result = models.TrackingResult(
            camera_id=camera_id,
            trajectory_data=job["trajectory"],
            zone_occupancy=job["zone_occupancy"],
            heatmap_s3_key=heatmap_s3_key,
        )
        db.add(result)
        await db.flush()


@router.get("/{store_id}/cameras/{camera_id}/tracking/trajectory")
async def get_trajectory(store_id: str, camera_id: str, db: AsyncSession = Depends(get_db)):
    cam = await db.get(models.Camera, camera_id)
    if not cam or cam.store_id != store_id:
        raise HTTPException(404, "Camera not found")

    if camera_id in _jobs and _jobs[camera_id].get("trajectory"):
        return {"trajectory": _jobs[camera_id]["trajectory"]}

    result = next((r for r in reversed(cam.tracking_results) if r.trajectory_data), None)
    if not result:
        return {"trajectory": []}
    return {"trajectory": result.trajectory_data}
