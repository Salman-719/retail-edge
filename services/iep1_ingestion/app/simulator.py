from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .bus import JsonEventProducer
from .events import FrameRefEvent, FrameReference

FRAME_REF_TOPIC = "vision.frame_ref.v1"


@dataclass
class CameraSimulation:
    camera_id: uuid.UUID
    camera_config_id: uuid.UUID
    video_path: Path
    source_fps: float
    frame_count: int
    width: int
    height: int


def _read_video_metadata(video_path: Path) -> dict[str, Any]:
    try:
        import cv2
    except Exception as exc:
        raise RuntimeError("opencv-python-headless is required for the Test1 simulator") from exc

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")
    try:
        return {
            "source_fps": float(cap.get(cv2.CAP_PROP_FPS) or 30.0),
            "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        }
    finally:
        cap.release()


def load_test1_cameras(test1_dir: str | Path) -> list[CameraSimulation]:
    root = Path(test1_dir)
    paths = [root / "Camera1.mp4", root / "Camera2.mp4"]
    cameras = []
    for path in paths:
        metadata = _read_video_metadata(path)
        cameras.append(
            CameraSimulation(
                camera_id=uuid.uuid4(),
                camera_config_id=uuid.uuid4(),
                video_path=path,
                source_fps=metadata["source_fps"],
                frame_count=metadata["frame_count"],
                width=metadata["width"],
                height=metadata["height"],
            )
        )
    return cameras


async def publish_test1_frames(
    producer: JsonEventProducer,
    *,
    test1_dir: str | Path,
    store_id: uuid.UUID,
    version_id: uuid.UUID,
    section_id: uuid.UUID,
    sample_rate_fps: float,
    max_frames_per_camera: int | None,
    realtime: bool,
    status: dict[str, Any],
) -> None:
    cameras = load_test1_cameras(test1_dir)
    if not cameras:
        raise RuntimeError(f"No Test1 cameras found in {test1_dir}")

    durations = [
        (camera.frame_count - 1) / camera.source_fps
        for camera in cameras
        if camera.frame_count > 0 and camera.source_fps > 0
    ]
    timeline_frames = int(min(durations) * sample_rate_fps) + 1 if durations else max_frames_per_camera
    if max_frames_per_camera is not None:
        timeline_frames = min(timeline_frames or max_frames_per_camera, max_frames_per_camera)
    if timeline_frames is None:
        raise RuntimeError("Unable to determine frame count for Test1 simulator")

    status.update({
        "status": "running",
        "frames_expected": timeline_frames * len(cameras),
        "frames_published": 0,
        "cameras": [str(camera.camera_id) for camera in cameras],
    })

    await producer.start()
    start_ts = datetime.now(timezone.utc)
    try:
        for sequence in range(timeline_frames):
            timestamp_sec = sequence / sample_rate_fps
            source_ts = start_ts + timedelta(seconds=timestamp_sec)
            for camera in cameras:
                frame_index = min(
                    max(0, camera.frame_count - 1),
                    int(round(timestamp_sec * camera.source_fps)),
                )
                event = FrameRefEvent(
                    store_id=store_id,
                    version_id=version_id,
                    section_id=section_id,
                    camera_id=camera.camera_id,
                    camera_config_id=camera.camera_config_id,
                    source_ts=source_ts,
                    sequence=sequence,
                    frame_ref=FrameReference(
                        uri=str(camera.video_path),
                        frame_index=frame_index,
                        timestamp_sec=timestamp_sec,
                        width=camera.width,
                        height=camera.height,
                    ),
                )
                await producer.publish(
                    os.getenv("VISION_FRAME_REF_TOPIC", FRAME_REF_TOPIC),
                    event.event_key(),
                    event.to_event_dict(),
                )
                status["frames_published"] += 1

            status["progress"] = round(status["frames_published"] / max(status["frames_expected"], 1), 4)
            if realtime:
                await asyncio.sleep(1.0 / sample_rate_fps)

        status.update({"status": "complete", "progress": 1.0})
    finally:
        await producer.stop()
