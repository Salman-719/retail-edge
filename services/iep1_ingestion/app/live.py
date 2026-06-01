from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.config import get_settings
from common.s3 import S3Client
from pydantic import BaseModel, Field

from .bus import JsonEventProducer
from .eep_client import EepClient
from .events import FrameRefEvent, FrameReference
from .simulator import FRAME_REF_TOPIC

logger = logging.getLogger(__name__)


class CameraStreamSpec(BaseModel):
    section_id: uuid.UUID
    camera_id: uuid.UUID
    camera_config_id: uuid.UUID
    stream_url: str
    name: str | None = None


class LiveStreamRunRequest(BaseModel):
    store_id: uuid.UUID
    version_id: uuid.UUID
    cameras: list[CameraStreamSpec]
    sample_rate_fps: float = Field(2.0, gt=0, le=30)
    max_frames_per_camera: int | None = Field(None, gt=0, le=100000)


async def _store_frame(
    cv2: Any,
    frame: Any,
    *,
    run_id: str,
    camera_id: str,
    sequence: int,
    frame_dir: Path,
    s3_client: S3Client | None,
) -> str:
    if s3_client is not None:
        key = f"vision-frames/{run_id}/{camera_id}/frame_{sequence:012d}.jpg"
        settings = get_settings()
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), settings.iep1_jpeg_quality])
        if not ok:
            raise RuntimeError("Unable to encode frame as JPEG")
        return await s3_client.put_bytes(key, encoded.tobytes(), "image/jpeg")

    path = frame_dir / f"frame_{sequence:012d}.jpg"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, cv2.imwrite, str(path), frame)
    return str(path)


def cameras_from_topology(topology: dict[str, Any]) -> LiveStreamRunRequest:
    cameras = []
    for section in topology.get("sections", []):
        for camera in section.get("cameras", []):
            stream_url = camera.get("stream_url")
            if not stream_url:
                continue
            cameras.append(
                CameraStreamSpec(
                    section_id=section["section_id"],
                    camera_id=camera["camera_id"],
                    camera_config_id=camera["camera_config_id"],
                    stream_url=stream_url,
                    name=camera.get("name"),
                )
            )
    return LiveStreamRunRequest(store_id=topology["store_id"], version_id=topology["version_id"], cameras=cameras)


async def _publish_camera(
    producer: JsonEventProducer,
    eep_client: EepClient,
    *,
    run_id: str,
    request: LiveStreamRunRequest,
    camera: CameraStreamSpec,
    status: dict[str, Any],
) -> None:
    try:
        import cv2
    except Exception as exc:
        raise RuntimeError("opencv-python-headless is required for live stream ingestion") from exc

    camera_key = str(camera.camera_id)
    retry_seconds = float(os.getenv("IEP1_STREAM_RETRY_SECONDS", "10"))
    cap = cv2.VideoCapture(camera.stream_url)
    _retry_count = 0
    while not cap.isOpened():
        _retry_count += 1
        if _retry_count == 1 or _retry_count % 6 == 0:
            logger.warning("Camera %s offline, retry %d (url=%s)", camera_key, _retry_count, camera.stream_url)
        await eep_client.post_camera_health({
            "store_id": str(request.store_id),
            "section_id": str(camera.section_id),
            "camera_id": camera_key,
            "camera_config_id": str(camera.camera_config_id),
            "status": "offline",
            "last_error": f"Unable to open stream: {camera.stream_url}",
        })
        status.setdefault("camera_errors", {})[camera_key] = "Unable to open stream"
        await asyncio.sleep(retry_seconds)
        cap.release()
        cap = cv2.VideoCapture(camera.stream_url)

    frame_dir = Path(os.getenv("IEP1_FRAME_CACHE_DIR", "/app/runtime/frame-cache")) / run_id / camera_key
    frame_dir.mkdir(parents=True, exist_ok=True)
    s3_client = S3Client(get_settings()) if os.getenv("IEP1_FRAME_STORAGE", "filesystem").lower() == "s3" else None
    period = 1.0 / request.sample_rate_fps
    sequence = 0
    try:
        await eep_client.post_camera_health({
            "store_id": str(request.store_id),
            "section_id": str(camera.section_id),
            "camera_id": camera_key,
            "camera_config_id": str(camera.camera_config_id),
            "status": "online",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        })
        while request.max_frames_per_camera is None or sequence < request.max_frames_per_camera:
            ok, frame = cap.read()
            if not ok:
                await eep_client.post_camera_health({
                    "store_id": str(request.store_id),
                    "section_id": str(camera.section_id),
                    "camera_id": camera_key,
                    "camera_config_id": str(camera.camera_config_id),
                    "status": "degraded",
                    "last_error": "Frame read failed",
                })
                await asyncio.sleep(period)
                continue

            status.setdefault("camera_errors", {}).pop(camera_key, None)
            source_ts = datetime.now(timezone.utc)
            frame_uri = await _store_frame(
                cv2,
                frame,
                run_id=run_id,
                camera_id=camera_key,
                sequence=sequence,
                frame_dir=frame_dir,
                s3_client=s3_client,
            )
            height, width = frame.shape[:2]
            event = FrameRefEvent(
                store_id=request.store_id,
                version_id=request.version_id,
                section_id=camera.section_id,
                camera_id=camera.camera_id,
                camera_config_id=camera.camera_config_id,
                source_ts=source_ts,
                sequence=sequence,
                frame_ref=FrameReference(uri=frame_uri, width=width, height=height),
            )
            await producer.publish(
                os.getenv("VISION_FRAME_REF_TOPIC", FRAME_REF_TOPIC),
                event.event_key(),
                event.to_event_dict(),
            )
            status["frames_published"] += 1
            status["camera_frames"][camera_key] = status["camera_frames"].get(camera_key, 0) + 1
            status["last_frame_at"] = source_ts.isoformat()
            sequence += 1
            await asyncio.sleep(period)
    finally:
        cap.release()


async def publish_live_streams(
    producer: JsonEventProducer,
    eep_client: EepClient,
    *,
    run_id: str,
    request: LiveStreamRunRequest,
    status: dict[str, Any],
) -> None:
    if not request.cameras:
        raise RuntimeError("No cameras with stream URLs were provided")

    status.update({
        "status": "running",
        "frames_expected": None if request.max_frames_per_camera is None else request.max_frames_per_camera * len(request.cameras),
        "frames_published": 0,
        "camera_frames": {},
        "camera_errors": {},
        "cameras": [str(camera.camera_id) for camera in request.cameras],
    })

    await producer.start()
    try:
        await asyncio.gather(*[
            _publish_camera(
                producer,
                eep_client,
                run_id=run_id,
                request=request,
                camera=camera,
                status=status,
            )
            for camera in request.cameras
        ])
        status.update({"status": "complete", "progress": 1.0})
    finally:
        await producer.stop()
