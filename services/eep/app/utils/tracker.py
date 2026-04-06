"""Background tracking worker — YOLO + ByteTrack per-camera job."""
import cv2
import numpy as np
from typing import List, Dict

from app.utils.homography import project_point


def point_in_polygon(x: float, y: float, polygon: List[Dict]) -> bool:
    """Ray-casting point-in-polygon test. Points in meters."""
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
    job: dict,
    video_path: str,
    homography_matrix: List[List[float]],
    zones_data: List[Dict],
    pixels_per_meter: float,
    model_size: str = "yolov8n",
) -> None:
    """
    Background thread entry point.  Mutates *job* in-place:
      job["status"]        → "running" | "done" | "error"
      job["progress"]      → 0–100
      job["total_frames"]  → int
      job["frames"]        → list[bytes]  (JPEG, capped at 60 to bound memory)
      job["trajectory"]    → list[dict]   (meters, sampled)
      job["zone_occupancy"]→ dict[name -> {seconds, percent}]
      job["error"]         → str | None
    """
    # lazy import so startup is fast
    from ultralytics import YOLO

    try:
        # ── Video probe ───────────────────────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        job["total_frames"] = max(total_frames, 1)

        H = np.array(homography_matrix, dtype=np.float64)

        model_name = model_size if model_size.endswith(".pt") else f"{model_size}.pt"
        model = YOLO(model_name)

        SAMPLE_EVERY = 3
        MAX_FRAMES_BUFFERED = 60  # cap in-memory MJPEG buffer

        trajectory: List[Dict] = []
        zone_presence: Dict[str, Dict[int, set]] = {z["name"]: {} for z in zones_data}

        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model.track(
                frame,
                persist=True,
                classes=[0],          # person only (COCO class 0)
                conf=0.3,
                iou=0.5,
                tracker="bytetrack.yaml",
                verbose=False,
            )

            annotated = results[0].plot()

            # Encode as JPEG and append; evict oldest if buffer full
            ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                if len(job["frames"]) >= MAX_FRAMES_BUFFERED:
                    job["frames"].pop(0)
                job["frames"].append(buf.tobytes())

            # Analytics: sample every Nth frame
            if frame_idx % SAMPLE_EVERY == 0 and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.cpu().numpy().astype(int)

                for box, tid in zip(boxes, track_ids):
                    cx = float((box[0] + box[2]) / 2)
                    cy = float(box[3])  # foot position

                    mx, my = project_point(H, cx, cy)
                    trajectory.append(
                        {"frameIdx": frame_idx, "x": mx, "y": my, "trackId": int(tid)}
                    )

                    matched_zone = None
                    for zone in zones_data:
                        if point_in_polygon(mx, my, zone["points"]):
                            matched_zone = zone

                    if matched_zone:
                        zname = matched_zone["name"]
                        tid_int = int(tid)
                        if tid_int not in zone_presence[zname]:
                            zone_presence[zname][tid_int] = set()
                        zone_presence[zname][tid_int].add(frame_idx)

            frame_idx += 1
            job["progress"] = int(frame_idx / job["total_frames"] * 100)

        cap.release()

        # ── Zone occupancy statistics ─────────────────────────────────────────
        effective_fps = fps / SAMPLE_EVERY
        total_person_frames = sum(
            len(v) for frames in zone_presence.values() for v in frames.values()
        )
        zone_occupancy: Dict = {}
        for zone in zones_data:
            zname = zone["name"]
            frames_in_zone = sum(len(v) for v in zone_presence[zname].values())
            seconds = frames_in_zone / effective_fps if effective_fps > 0 else 0.0
            pct = (
                (frames_in_zone / total_person_frames * 100)
                if total_person_frames > 0
                else 0.0
            )
            zone_occupancy[zname] = {
                "seconds": round(seconds, 1),
                "percent": round(pct, 1),
            }

        job["trajectory"] = trajectory
        job["zone_occupancy"] = zone_occupancy
        job["progress"] = 100
        job["status"] = "done"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(exc)
