"""Video ingestion endpoints — upload, metadata extraction, frame extraction."""
import os
import logging
from pathlib import Path

import cv2
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import Response

from app.core.config import settings
from app.core.s3_client import s3_client
from app.core.database import AsyncSessionLocal
from app.core.metrics import video_uploads, video_upload_bytes, video_duration_seconds, frame_extraction_duration

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_camera(store_id: str, camera_id: str) -> dict:
    """Fetch camera row from DB. Returns dict or raises 404."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa.text("SELECT id, store_id, video_s3_key FROM cameras WHERE id = :id"),
            {"id": camera_id},
        )
        row = result.mappings().first()
    if not row or row["store_id"] != store_id:
        raise HTTPException(404, "Camera not found")
    return dict(row)


async def _update_camera_video(camera_id: str, s3_key: str, fps: float, duration: float, width: int, height: int):
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa.text(
                "UPDATE cameras SET video_s3_key=:key, video_fps=:fps, video_duration=:dur, "
                "video_width=:w, video_height=:h, updated_at=now() WHERE id=:id"
            ),
            {"key": s3_key, "fps": fps, "dur": duration, "w": width, "h": height, "id": camera_id},
        )
        await session.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{store_id}/cameras/{camera_id}/video")
async def upload_video(
    store_id: str,
    camera_id: str,
    file: UploadFile = File(...),
):
    await _get_camera(store_id, camera_id)  # validates existence

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

    s3_key = f"stores/{store_id}/cameras/{camera_id}/video{ext}"
    s3_client.upload_file(s3_key, tmp_path, content_type="video/mp4")
    video_upload_bytes.inc(len(raw))
    os.remove(tmp_path)

    await _update_camera_video(camera_id, s3_key, fps, duration, width, height)
    video_uploads.labels(status="success").inc()
    video_duration_seconds.observe(duration)

    return {
        "camera_id": camera_id,
        "video_s3_key": s3_key,
        "video_fps": fps,
        "video_duration": duration,
        "video_width": width,
        "video_height": height,
    }


@router.get("/{store_id}/cameras/{camera_id}/frame")
async def get_frame(
    store_id: str,
    camera_id: str,
    timestamp_sec: float = Query(0.0),
):
    """Extract and return a JPEG frame at the given timestamp."""
    cam = await _get_camera(store_id, camera_id)
    if not cam.get("video_s3_key"):
        raise HTTPException(404, "No video uploaded for this camera")

    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = Path(cam["video_s3_key"]).suffix
    tmp_path = os.path.join(tmp_dir, f"frame_{camera_id}{ext}")

    try:
        with frame_extraction_duration.time():
            s3_client.download_to_file(cam["video_s3_key"], tmp_path)
            cap = cv2.VideoCapture(tmp_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp_sec * fps))
            ret, frame = cap.read()
            cap.release()

        if not ret:
            raise HTTPException(400, "Could not read frame at given timestamp")

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
