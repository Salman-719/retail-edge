"""IEP2 pipeline owner — models, orchestration, stream interface.

FastAPI is a thin transport adapter. This module is the only place the
full pipeline runs. It has zero FastAPI imports.

Usage (symmetric across all callers):
    with runtime.run(video_path, camera_id) as stream:
        for result in stream:
            ...          # result is a FrameResult
"""
import base64
import io
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

log = logging.getLogger("iep2.runtime")

import cv2
import numpy as np
from PIL import Image

try:
    from .detector.detector import load_model as _load_yolo, detect
    from .reid.reid import load_model as _load_reid
    from .tracker.tracker import create_tracker, update
    from .video_ingestor.ingestor import extract_frames
    from .identity.manager import LocalIdentityManager
    from .persistence.postgres import TrackingPersistence
except ImportError:
    _root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _root)
    from detector.detector import load_model as _load_yolo, detect
    from reid.reid import load_model as _load_reid
    from tracker.tracker import create_tracker, update
    from video_ingestor.ingestor import extract_frames
    from identity.manager import LocalIdentityManager
    from persistence.postgres import TrackingPersistence

_MAX_WIRE_WIDTH = 640


@dataclass
class FrameResult:
    frame_index: int
    frame_b64:   str
    tracks:      list   # list[dict]: {track_id, local_id, label, confidence, bbox}
    new_entries: list   # list[int]: track_ids seen for the first time this frame


def _encode_frame(frame: np.ndarray) -> tuple[str, float]:
    """Resize to max 640px wide, base64-encode as JPEG.

    Returns (base64_jpeg, scale) — scale maps original bbox coords to
    the encoded image's coordinate space.
    """
    h, w = frame.shape[:2]
    scale = 1.0
    if w > _MAX_WIRE_WIDTH:
        scale = _MAX_WIRE_WIDTH / w
        frame = cv2.resize(frame, (_MAX_WIRE_WIDTH, int(h * scale)))
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), scale


class IEP2Runtime:
    def __init__(self):
        """Load all models once. Reused across every run() call."""
        log.info("Loading YOLO model (%s)…", "yolov8n.pt")
        self.yolo_model = _load_yolo()
        log.info("YOLO loaded.")
        log.info("Loading ReID model (osnet_x1_0)…")
        self.reid_model = _load_reid()
        log.info("ReID loaded.")

    @contextmanager
    def run(self, video_path: str, camera_id: str):
        """Context manager that yields the frame stream.

        DB lifetime is owned here — close() is guaranteed in finally.
        """
        log.info("Opening DB connection  camera=%s", camera_id)
        db = TrackingPersistence(os.getenv("DATABASE_URL", ""), camera_id)
        db.create_table()
        try:
            yield self._stream(video_path, camera_id, db)
        finally:
            db.close()
            log.info("DB connection closed  camera=%s", camera_id)

    def _stream(self, video_path: str, camera_id: str, db: TrackingPersistence):
        """Private generator — all per-upload state lives here."""
        log.info("Stream started  video=%s  camera=%s", video_path, camera_id)
        tracker     = create_tracker()
        manager     = LocalIdentityManager(reid_model=self.reid_model)
        seen_ids: set[int] = set()
        frame_index = 0
        db_rows_written = 0

        for frame in extract_frames(video_path):
            detections = detect(self.yolo_model, frame)
            tracks     = update(tracker, detections)
            enriched   = manager.process_frame(frame, tracks)

            n_confirmed = sum(1 for t in enriched if t["local_id"] is not None)
            n_pending   = sum(1 for t in enriched if t["local_id"] is None)
            log.debug(
                "Frame %4d  detections=%d  tracks=%d  confirmed=%d  pending=%d",
                frame_index, len(detections), len(tracks), n_confirmed, n_pending,
            )

            # DB writes use original (pre-scale) coordinates.
            for track in enriched:
                if track["local_id"] is not None:
                    x1, y1, x2, y2 = [int(c) for c in track["bbox"]]
                    db.write_detection(
                        local_id=track["local_id"],
                        track_id=track["track_id"],
                        frame_index=frame_index,
                        x1=x1, y1=y1, x2=x2, y2=y2,
                        confidence=float(track["confidence"]),
                    )
                    db_rows_written += 1

            # Scale bboxes to encoded image space for the wire.
            frame_b64, scale = _encode_frame(frame)
            if scale != 1.0:
                display_tracks = [
                    {**t, "bbox": [c * scale for c in t["bbox"]]}
                    for t in enriched
                ]
            else:
                display_tracks = enriched

            new_entries = [t["track_id"] for t in enriched if t["track_id"] not in seen_ids]
            seen_ids.update(t["track_id"] for t in enriched)
            if new_entries:
                log.info("Frame %4d  new track_ids=%s", frame_index, new_entries)

            yield FrameResult(
                frame_index=frame_index,
                frame_b64=frame_b64,
                tracks=display_tracks,
                new_entries=new_entries,
            )
            frame_index += 1

        log.info(
            "Stream finished  camera=%s  frames=%d  db_rows=%d",
            camera_id, frame_index, db_rows_written,
        )


# ---------------------------------------------------------------------------
# Standalone: python runtime.py <video_path> <camera_id>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) != 3:
        print("usage: python runtime.py <video_path> <camera_id>")
        sys.exit(1)

    load_dotenv()
    video_path = sys.argv[1]
    camera_id  = sys.argv[2]

    runtime = IEP2Runtime()
    with runtime.run(video_path, camera_id) as stream:
        for result in stream:
            n_confirmed = sum(1 for t in result.tracks if t["local_id"] is not None)
            n_pending   = sum(1 for t in result.tracks if t["local_id"] is None)
            print(
                f"frame={result.frame_index:4d}  "
                f"confirmed={n_confirmed}  pending={n_pending}  "
                f"new_track_ids={result.new_entries}"
            )
    print("done")
