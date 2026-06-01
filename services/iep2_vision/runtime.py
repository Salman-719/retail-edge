"""IEP2 pipeline owner — models, orchestration, stream interface.

FastAPI is a thin transport adapter. This module is the only place the
full pipeline runs. It has zero FastAPI imports.

Usage (video file):
    with runtime.run(video_path) as stream:
        for result in stream: ...

Usage (live from IEP1):
    with runtime.run_from_iep1() as stream:
        for result in stream: ...
"""
import base64
import io
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Tuple

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
    from .ingest.redis_source import RedisStreamFrameSource, make_s3_client
    from .live_publisher import LivePublisher
except ImportError:
    _root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _root)
    from detector.detector import load_model as _load_yolo, detect
    from reid.reid import load_model as _load_reid
    from tracker.tracker import create_tracker, update
    from video_ingestor.ingestor import extract_frames
    from identity.manager import LocalIdentityManager
    from persistence.postgres import TrackingPersistence
    from ingest.redis_source import RedisStreamFrameSource, make_s3_client
    from live_publisher import LivePublisher

_MAX_WIRE_WIDTH = 640


@dataclass
class Iep2Settings:
    store_id:            str
    camera_id:           str
    database_url:        str
    redis_url:           str   = "redis://localhost:6379/0"
    s3_endpoint_url:     str   = ""
    s3_access_key:       str   = ""
    s3_secret_key:       str   = ""
    s3_bucket:           str   = "retailvision"
    target_fps:          float = 5.0
    live_stream_enabled: bool  = True


@dataclass
class FrameResult:
    frame_index: int
    frame_b64:   str
    tracks:      list   # list[dict]: {track_id, local_id, label, confidence, bbox}
    new_entries: list   # list[int]: track_ids seen for the first time this frame


def _encode_frame(frame: np.ndarray) -> Tuple[str, float]:
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
    def __init__(self, settings: Iep2Settings):
        """Load all models once. All config fixed at construction via settings."""
        self.settings = settings
        log.info("Loading YOLO model (%s)…", "yolov8n.pt")
        self.yolo_model = _load_yolo()
        log.info("YOLO loaded.")
        log.info("Loading ReID model (osnet_x1_0)…")
        self.reid_model = _load_reid()
        log.info("ReID loaded.")

    @contextmanager
    def run(self, video_path: str, start_ms: int = 0):
        """Context manager that yields the frame stream from a video file."""
        camera_id = self.settings.camera_id
        log.info("Opening DB connection  camera=%s", camera_id)
        db = TrackingPersistence(self.settings.database_url, camera_id)
        db.create_table()
        self._start_ms = start_ms
        try:
            yield self._stream_from_source(self._video_source(video_path), db)
        finally:
            db.close()
            log.info("DB connection closed  camera=%s", camera_id)

    @contextmanager
    def run_from_iep1(self):
        """Context manager that yields the frame stream from IEP1 via Redis + S3."""
        camera_id = self.settings.camera_id
        s3 = make_s3_client(
            self.settings.s3_endpoint_url,
            self.settings.s3_access_key,
            self.settings.s3_secret_key,
        )
        source = RedisStreamFrameSource(
            camera_id,
            self.settings.redis_url,
            s3,
            self.settings.s3_bucket,
        )
        live_pub = (
            LivePublisher(camera_id, self.settings.redis_url, enabled=True)
            if self.settings.live_stream_enabled
            else None
        )
        log.info("Opening DB connection  camera=%s", camera_id)
        db = TrackingPersistence(self.settings.database_url, camera_id)
        db.create_table()
        try:
            yield self._stream_from_source(source.frames(), db, live_pub=live_pub)
        finally:
            source.release()
            db.close()
            log.info("DB connection closed  camera=%s", camera_id)

    @staticmethod
    def _video_source(video_path: str) -> Iterator[Tuple[int, np.ndarray]]:
        """Wrap video file frames as (capture_ts_ms, s3_key, frame) — ts and key are placeholders."""
        for frame in extract_frames(video_path):
            yield 0, None, frame

    def _stream_from_source(
        self,
        source: Iterator[Tuple[int, np.ndarray]],
        db: TrackingPersistence,
        live_pub=None,
    ):
        """Single pipeline implementation — both run() and run_from_iep1() use this."""
        camera_id = self.settings.camera_id
        log.info("Stream started  camera=%s", camera_id)
        tracker     = create_tracker()
        manager     = LocalIdentityManager(reid_model=self.reid_model)
        seen_ids: set = set()
        frame_index = 0
        db_rows_written = 0

        for _capture_ts_ms, _s3_key, frame in source:
            detections = detect(self.yolo_model, frame)
            tracks     = update(tracker, detections)
            enriched   = manager.process_frame(frame, tracks)

            n_confirmed = sum(1 for t in enriched if t["local_id"] is not None)
            n_pending   = sum(1 for t in enriched if t["local_id"] is None)
            log.debug(
                "Frame %4d  detections=%d  tracks=%d  confirmed=%d  pending=%d",
                frame_index, len(detections), len(tracks), n_confirmed, n_pending,
            )

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

            if live_pub:
                live_pub.publish(_s3_key or "", _capture_ts_ms, display_tracks)

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
# Standalone: python runtime.py <video_path>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("usage: python runtime.py <video_path>")
        sys.exit(1)

    settings = Iep2Settings(
        store_id="test",
        camera_id="cam0",
        database_url=os.environ.get("DATABASE_URL", ""),
    )
    runtime = IEP2Runtime(settings)
    with runtime.run(sys.argv[1]) as stream:
        for result in stream:
            print(f"frame={result.frame_index} tracks={len(result.tracks)}")
