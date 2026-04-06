import cv2
import numpy as np
import threading
import queue as queue_module
from pathlib import Path
from ultralytics import YOLO
from typing import List, Dict, Any, Optional

from homography import project_point


def point_in_polygon(x: float, y: float, polygon: List[Dict]) -> bool:
    """Ray-casting point-in-polygon test. Points in meters."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]['x'], polygon[i]['y']
        xj, yj = polygon[j]['x'], polygon[j]['y']
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


# Global store: camera_id -> job dict
tracking_jobs: Dict[str, dict] = {}


def get_job(camera_id: str) -> Optional[dict]:
    return tracking_jobs.get(camera_id)


def start_tracking_job(
    camera_id: str,
    video_path: Path,
    homography_matrix: List[List[float]],
    zones: List[Dict],
    model_size: str = 'n',
    pixels_per_meter: float = 100.0,
    origin_px: dict = None,
    floor_plan_path: Path = None,
    heatmap_output_path: Path = None,
) -> dict:
    """
    Start a background tracking job and return the job dict immediately.
    The job processes every frame with YOLO+ByteTrack, puts annotated frames
    into a queue for MJPEG streaming, and accumulates trajectory/occupancy data.
    """
    H = np.array(homography_matrix, dtype=np.float64)

    cap_probe = cv2.VideoCapture(str(video_path))
    fps = cap_probe.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap_probe.get(cv2.CAP_PROP_FRAME_COUNT))
    cap_probe.release()

    job = {
        'status': 'starting',
        'camera_id': camera_id,
        'video_path': str(video_path),
        'fps': fps,
        'total_frames': max(total_frames, 1),
        'processed_frames': 0,
        # Frame queue: ('frame', np.ndarray) | ('done', None) | ('error', str)
        'frame_queue': queue_module.Queue(maxsize=90),
        'trajectory_pixels': [],
        'trajectory_meters': [],
        'zone_presence': {z['name']: {} for z in zones},
        'zone_occupancy': {},
        'heatmap_url': None,
        'error': None,
        # Stored for heatmap generation inside the worker
        'zones': zones,
        'pixels_per_meter': pixels_per_meter,
        'origin_px': origin_px or {'x': 0, 'y': 0},
        'floor_plan_path': str(floor_plan_path) if floor_plan_path else None,
        'heatmap_output_path': str(heatmap_output_path) if heatmap_output_path else None,
    }
    tracking_jobs[camera_id] = job

    thread = threading.Thread(
        target=_tracking_worker,
        args=(job, H, zones, model_size),
        daemon=True,
    )
    thread.start()
    return job


def _tracking_worker(job: dict, H: np.ndarray, zones: List[Dict], model_size: str):
    """
    Background thread: reads every frame, runs YOLO+ByteTrack, draws bounding
    boxes, pushes annotated frames to the queue, and accumulates analytics.
    """
    try:
        model = YOLO(f'yolov8{model_size}.pt')
        cap = cv2.VideoCapture(job['video_path'])
        fps = job['fps']

        job['status'] = 'running'

        # Collect trajectory data every 3rd frame to reduce overhead
        SAMPLE_EVERY = 3
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Run tracking on every frame so the stream stays smooth
            results = model.track(
                frame,
                persist=True,
                classes=[0],           # person class in COCO
                conf=0.3,
                iou=0.5,
                tracker='bytetrack.yaml',
                verbose=False,
            )

            # Annotated frame: bounding boxes + track IDs drawn by ultralytics
            annotated = results[0].plot()

            # Push to queue; if full, evict oldest to keep stream live
            try:
                job['frame_queue'].put_nowait(('frame', annotated))
            except queue_module.Full:
                try:
                    job['frame_queue'].get_nowait()
                except queue_module.Empty:
                    pass
                try:
                    job['frame_queue'].put_nowait(('frame', annotated))
                except queue_module.Full:
                    pass

            # Accumulate analytics on sampled frames
            if frame_idx % SAMPLE_EVERY == 0 and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.cpu().numpy().astype(int)

                for box, tid in zip(boxes, track_ids):
                    cx = float((box[0] + box[2]) / 2)
                    cy = float(box[3])   # bottom-centre = foot position

                    job['trajectory_pixels'].append(
                        {'frameIdx': frame_idx, 'x': cx, 'y': cy, 'trackId': int(tid)}
                    )

                    mx, my = project_point(H, cx, cy)
                    job['trajectory_meters'].append(
                        {'frameIdx': frame_idx, 'x': mx, 'y': my, 'trackId': int(tid)}
                    )

                    # Last-zone-wins: newest zone takes the point in overlapping areas
                    matched_zone = None
                    for zone in zones:
                        if point_in_polygon(mx, my, zone['points']):
                            matched_zone = zone

                    if matched_zone:
                        zname = matched_zone['name']
                        tid_int = int(tid)
                        if tid_int not in job['zone_presence'][zname]:
                            job['zone_presence'][zname][tid_int] = set()
                        job['zone_presence'][zname][tid_int].add(frame_idx)

            job['processed_frames'] = frame_idx + 1
            frame_idx += 1

        cap.release()

        # ── Final zone occupancy statistics ───────────────────────────────
        effective_fps = fps / SAMPLE_EVERY
        total_person_frames = sum(
            len(v) for frames in job['zone_presence'].values() for v in frames.values()
        )
        for zone in zones:
            zname = zone['name']
            frames_in_zone = sum(len(v) for v in job['zone_presence'][zname].values())
            seconds = frames_in_zone / effective_fps if effective_fps > 0 else 0
            pct = (frames_in_zone / total_person_frames * 100) if total_person_frames > 0 else 0
            job['zone_occupancy'][zname] = {
                'seconds': round(seconds, 1),
                'percent': round(pct, 1),
            }

        # ── Generate heatmap with zone coloring ───────────────────────────
        if job['floor_plan_path'] and job['heatmap_output_path']:
            try:
                from heatmap import generate_heatmap
                generate_heatmap(
                    camera_id=job['camera_id'],
                    trajectory_meters=job['trajectory_meters'],
                    floor_plan_path=Path(job['floor_plan_path']),
                    pixels_per_meter=job['pixels_per_meter'],
                    origin_px=job['origin_px'],
                    output_path=Path(job['heatmap_output_path']),
                    zones=zones,
                    zone_occupancy=job['zone_occupancy'],
                )
                job['heatmap_url'] = f"/uploads/heatmaps/{job['camera_id']}.png"
            except Exception as e:
                print(f'[tracker] heatmap generation error: {e}')

        job['status'] = 'done'
        job['frame_queue'].put(('done', None))

    except Exception as e:
        import traceback
        traceback.print_exc()
        job['status'] = 'error'
        job['error'] = str(e)
        try:
            job['frame_queue'].put(('error', str(e)))
        except Exception:
            pass
