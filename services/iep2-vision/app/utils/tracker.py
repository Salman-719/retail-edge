"""Background tracking worker — YOLO + ByteTrack per-camera job.

Job state is persisted to Redis so EEP can poll it independently.
In-memory frame buffer is kept here for MJPEG streaming (can't go in Redis).
"""
import time
import cv2
import numpy as np
from typing import List, Dict

from app.utils.homography import project_point
from app.core.redis_client import sync_redis
from app.core.metrics import (
    tracking_jobs, tracking_job_duration,
    tracking_frames_processed, tracking_detections,
    active_tracking_jobs,
)


def point_in_polygon(x: float, y: float, polygon: List[Dict]) -> bool:
    """Ray-casting point-in-polygon test. Points in metres."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["x"], polygon[i]["y"]
        xj, yj = polygon[j]["x"], polygon[j]["y"]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi
        ):
            inside = not inside
        j = i
    return inside


def run_tracking_job(
    frame_buffer: list,
    camera_id: str,
    store_id: str,
    video_path: str,
    homography_matrix: List[List[float]],
    zones_data: List[Dict],
    pixels_per_meter: float,
    model_size: str = "yolov8n",
) -> None:
    """
    Background thread entry point.

    Writes job state to Redis:
      status, progress, total_frames, zone_occupancy, trajectory, error

    Appends JPEG bytes to frame_buffer (in-memory, for MJPEG stream).
    """
    from ultralytics import YOLO

    active_tracking_jobs.inc()
    job_start = time.time()

    sync_redis.set_job(camera_id, {
        "status": "running",
        "progress": 0,
        "total_frames": 0,
        "zone_occupancy": {},
        "trajectory": [],
        "error": "",
        "store_id": store_id,
        "camera_id": camera_id,
    })

    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_frames = max(total_frames, 1)
        sync_redis.update_job(camera_id, total_frames=total_frames)

        H = np.array(homography_matrix, dtype=np.float64)
        model_name = model_size if model_size.endswith(".pt") else f"{model_size}.pt"
        model = YOLO(model_name)

        SAMPLE_EVERY = 3
        OCCUPANCY_UPDATE_EVERY = 30   # push live occupancy to Redis every 30 sampled frames
        MAX_FRAMES_BUFFERED = 60

        trajectory: List[Dict] = []
        zone_presence: Dict[str, Dict[int, set]] = {z["name"]: {} for z in zones_data}
        frame_idx = 0
        sample_count = 0

        def _compute_occupancy() -> Dict:
            effective_fps = fps / SAMPLE_EVERY
            total_person_frames = sum(
                len(v) for frames in zone_presence.values() for v in frames.values()
            )
            occ: Dict = {}
            for zone in zones_data:
                zname = zone["name"]
                frames_in_zone = sum(len(v) for v in zone_presence[zname].values())
                seconds = frames_in_zone / effective_fps if effective_fps > 0 else 0.0
                pct = (frames_in_zone / total_person_frames * 100) if total_person_frames > 0 else 0.0
                occ[zname] = {"seconds": round(seconds, 1), "percent": round(pct, 1)}
            return occ

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model.track(
                frame,
                persist=True,
                classes=[0],
                conf=0.3,
                iou=0.5,
                tracker="botsort.yaml",  # appearance ReID — re-assigns same ID on re-entry
                verbose=False,
            )
            annotated = results[0].plot()

            ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                if len(frame_buffer) >= MAX_FRAMES_BUFFERED:
                    frame_buffer.pop(0)
                frame_buffer.append(buf.tobytes())

            if frame_idx % SAMPLE_EVERY == 0 and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.cpu().numpy().astype(int)

                for box, tid in zip(boxes, track_ids):
                    cx = float((box[0] + box[2]) / 2)
                    cy = float(box[3])
                    mx, my = project_point(H, cx, cy)
                    trajectory.append({"frameIdx": frame_idx, "x": mx, "y": my, "trackId": int(tid)})

                    for zone in zones_data:
                        if point_in_polygon(mx, my, zone["points"]):
                            zname = zone["name"]
                            tid_int = int(tid)
                            if tid_int not in zone_presence[zname]:
                                zone_presence[zname][tid_int] = set()
                            zone_presence[zname][tid_int].add(frame_idx)
                            break

                tracking_detections.inc(len(results[0].boxes.id))
                sample_count += 1

                # Push live occupancy periodically so frontend sees updates during tracking
                if sample_count % OCCUPANCY_UPDATE_EVERY == 0:
                    sync_redis.update_job(camera_id, zone_occupancy=_compute_occupancy())

            frame_idx += 1
            tracking_frames_processed.inc()
            sync_redis.update_job(camera_id, progress=int(frame_idx / total_frames * 100))

        cap.release()

        zone_occupancy = _compute_occupancy()
        sync_redis.update_job(
            camera_id,
            trajectory=trajectory,
            zone_occupancy=zone_occupancy,
            progress=100,
            status="done",
        )
        tracking_jobs.labels(status="done").inc()
        tracking_job_duration.observe(time.time() - job_start)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        sync_redis.update_job(camera_id, status="error", error=str(exc))
        tracking_jobs.labels(status="error").inc()
        tracking_job_duration.observe(time.time() - job_start)

    finally:
        active_tracking_jobs.dec()
