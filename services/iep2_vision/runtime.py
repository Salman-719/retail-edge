"""IEP2 pipeline owner — models, orchestration, stream interface.

Usage (video file):
    async with runtime.run(video_path) as stream:
        async for result in stream: ...

Usage (live from IEP1):
    async with runtime.run_from_iep1() as stream:
        async for result in stream: ...
"""
import asyncio
import base64
import io
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Tuple

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
    from .persistence.postgres import PostgresPersistence
    from .projection.projector import FloorProjector
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
    from persistence.postgres import PostgresPersistence
    from projection.projector import FloorProjector
    from ingest.redis_source import RedisStreamFrameSource, make_s3_client
    from live_publisher import LivePublisher

_MAX_WIRE_WIDTH = 640


@dataclass
class Iep2Settings:
    store_id:            str
    camera_id:           str
    database_url_server: str        # plain postgresql:// — raw asyncpg, not SQLAlchemy format
    window_seconds:      float      # required — no default; must match IEP1 and IEP3
    camera_config_id:    str | None = None
    redis_url:           str        = "redis://localhost:6379/0"
    s3_endpoint_url:     str        = ""
    s3_access_key:       str        = ""
    s3_secret_key:       str        = ""
    s3_bucket:           str        = "retailvision"
    target_fps:          float      = 5.0
    live_stream_enabled: bool       = True


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


def _fetch_s3_frame(s3_client, bucket: str, key: str) -> np.ndarray | None:
    """Fetch a JPEG from S3 and decode to BGR ndarray. Returns None on failure."""
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
    except Exception as exc:
        log.warning("S3 fetch failed  key=%s: %s", key, exc)
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        log.warning("imdecode failed  key=%s", key)
    return frame


def _project_tracks(tracks: list[dict], projector: FloorProjector) -> None:
    """Project each confirmed track's bbox foot point and attach floor_x, floor_y, clamped in-place.

    Called after ByteTrack update, before identity manager, so the manager and
    the persist step both read projection results from the track dict rather than
    recomputing them independently.
    """
    for t in tracks:
        x1, y1, x2, y2 = [int(c) for c in t["bbox"]]
        res = projector.project_and_clamp(x1, y1, x2, y2)
        if res is not None:
            t["floor_x"] = res.x
            t["floor_y"] = res.y
            t["clamped"] = res.clamped
            t["floor_pos"] = (res.x, res.y)
        else:
            t["floor_x"] = None
            t["floor_y"] = None
            t["clamped"] = False
            t["floor_pos"] = None


async def _load_projector(persistence: PostgresPersistence, camera_config_id: str | None) -> FloorProjector:
    projector = FloorProjector()
    if camera_config_id:
        await projector.load(persistence.pool, uuid.UUID(camera_config_id))
    return projector


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

    @asynccontextmanager
    async def run(self, video_path: str, start_ms: int = 0):
        """Async context manager that yields the frame stream from a video file."""
        camera_id = self.settings.camera_id
        async with PostgresPersistence(
            database_url=self.settings.database_url_server,
            store_id=self.settings.store_id,
            camera_id=camera_id,
        ) as persistence:
            projector = await _load_projector(persistence, self.settings.camera_config_id)

            # Write stream resolution once before the processing loop starts.
            # Open a brief cap solely to read dimensions — extract_frames owns its own cap.
            _cap = cv2.VideoCapture(video_path)
            if _cap.isOpened():
                _w = int(_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                _h = int(_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                _cap.release()
                if _w > 0 and _h > 0:
                    await persistence.write_stream_resolution(camera_id, _w, _h)
                else:
                    log.warning(
                        "Could not read stream resolution from source "
                        "(width=%d height=%d) — stream_width/height not updated",
                        _w, _h,
                    )

            self._start_ms = start_ms
            yield self._stream_from_source(self._video_source(video_path), persistence, projector)

    @asynccontextmanager
    async def run_from_iep1(self):
        """Async context manager that yields the frame stream from IEP1 via Redis + S3."""
        camera_id = self.settings.camera_id
        s3 = make_s3_client(
            self.settings.s3_endpoint_url,
            self.settings.s3_access_key,
            self.settings.s3_secret_key,
        )
        live_pub = (
            LivePublisher(camera_id, self.settings.redis_url, enabled=True)
            if self.settings.live_stream_enabled
            else None
        )
        async with PostgresPersistence(
            database_url=self.settings.database_url_server,
            store_id=self.settings.store_id,
            camera_id=camera_id,
        ) as persistence:
            projector = await _load_projector(persistence, self.settings.camera_config_id)
            async with RedisStreamFrameSource(camera_id, self.settings.redis_url, s3) as source:
                yield self._stream_from_iep1(source, s3, self.settings.s3_bucket, persistence, projector, live_pub)

    @staticmethod
    def _video_source(video_path: str) -> Iterator[Tuple[int, str | None, np.ndarray]]:
        """Wrap video file frames as (capture_ts_ms, s3_key, frame)."""
        import time
        for frame in extract_frames(video_path):
            yield int(time.time() * 1000), None, frame

    async def _flush_centroids(
        self,
        manager: "LocalIdentityManager",
        persistence: "PostgresPersistence",
        batch_number: int,
    ) -> None:
        """Collect active centroids and UPSERT to local_centroids.

        Called once per batch window after all tracking_history rows are
        written and before XACK fires. Safe to call when no tracks are active.
        """
        active = manager.get_active_centroids()
        if not active:
            return

        records = [
            {
                "local_id":         str(uuid.UUID(int=local_id_int)),
                "camera_id":        self.settings.camera_id,
                "store_id":         self.settings.store_id,
                "centroid":         centroid_array.astype(np.float32).tobytes(),
                "updated_at_batch": batch_number,
            }
            for local_id_int, centroid_array in active.items()
        ]

        await persistence.upsert_local_centroids(records)
        log.debug(
            "Flushed %d centroids for batch %d camera %s",
            len(records), batch_number, self.settings.camera_id,
        )

    async def _publish_batch_complete(
        self,
        redis_client,
        batch_number: int,
        window_start_ms: int,
        window_end_ms: int,
    ) -> None:
        """XADD one batch_complete event to stream:iep2:batch_complete.

        Called after centroid flush and before XACK. A failed XADD is logged
        but does not prevent XACK — IEP3's coordinator timeout guard handles
        cameras that fail to report.
        """
        fields = {
            "camera_id":       self.settings.camera_id,
            "store_id":        self.settings.store_id,
            "batch_number":    str(batch_number),
            "window_start_ms": str(window_start_ms),
            "window_end_ms":   str(window_end_ms),
        }
        try:
            await redis_client.xadd("stream:iep2:batch_complete", fields)
            log.debug(
                "Published batch_complete  camera=%s  batch=%d  window=[%d, %d]",
                self.settings.camera_id, batch_number, window_start_ms, window_end_ms,
            )
        except Exception as exc:
            log.error(
                "Failed to publish batch_complete for batch %d camera %s: %s",
                batch_number, self.settings.camera_id, exc,
            )

    async def _run_frame_detections(
        self,
        enriched: list,
        capture_ts_ms: int,
        persistence: PostgresPersistence,
        projector: FloorProjector,
    ) -> int:
        """Insert all confirmed detections for one frame. Returns count of rows written."""
        rows = 0
        for track in enriched:
            if track["local_id"] is not None:
                x1, y1, x2, y2 = [int(c) for c in track["bbox"]]
                bbox_area = (x2 - x1) * (y2 - y1)
                local_id_uuid = uuid.UUID(int=track["local_id"])
                floor_x = track.get("floor_x")
                floor_y = track.get("floor_y")
                zone_id = (
                    projector.zone_of(floor_x, floor_y)
                    if floor_x is not None and floor_y is not None
                    else None
                )
                await persistence.insert_detection(
                    local_id=local_id_uuid,
                    timestamp_ms=capture_ts_ms,
                    bbox_confidence=float(track["confidence"]),
                    bbox_area=bbox_area,
                    floor_x=floor_x,
                    floor_y=floor_y,
                    zone_id=zone_id,
                )
                rows += 1
        return rows

    async def _stream_from_source(
        self,
        source: Iterator[Tuple[int, str | None, np.ndarray]],
        persistence: PostgresPersistence,
        projector: FloorProjector,
        live_pub=None,
    ) -> AsyncIterator[FrameResult]:
        """Async generator for the video-file pipeline path."""
        camera_id = self.settings.camera_id
        log.info("Stream started  camera=%s", camera_id)
        tracker        = create_tracker()
        manager        = LocalIdentityManager(reid_model=self.reid_model)
        seen_ids: set  = set()
        frame_index    = 0
        db_rows_written = 0

        for _capture_ts_ms, _s3_key, frame in source:
            detections = detect(self.yolo_model, frame)
            tracks     = update(tracker, detections)
            _project_tracks(tracks, projector)
            enriched   = manager.process_frame(frame, tracks)

            log.debug(
                "Frame %4d  detections=%d  tracks=%d  confirmed=%d  pending=%d",
                frame_index, len(detections), len(tracks),
                sum(1 for t in enriched if t["local_id"] is not None),
                sum(1 for t in enriched if t["local_id"] is None),
            )

            rows = await self._run_frame_detections(enriched, _capture_ts_ms, persistence, projector)
            db_rows_written += rows

            frame_b64, scale = _encode_frame(frame)
            display_tracks = (
                [{**t, "bbox": [c * scale for c in t["bbox"]]} for t in enriched]
                if scale != 1.0 else enriched
            )

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

    async def _stream_from_iep1(
        self,
        source: RedisStreamFrameSource,
        s3_client,
        s3_bucket: str,
        persistence: PostgresPersistence,
        projector: FloorProjector,
        live_pub=None,
    ) -> AsyncIterator[FrameResult]:
        """Async generator for the IEP1 Redis pipeline path with manifest-level XACK."""
        camera_id = self.settings.camera_id
        log.info("Stream started (IEP1)  camera=%s", camera_id)
        tracker        = create_tracker()
        manager        = LocalIdentityManager(reid_model=self.reid_model)
        seen_ids: set  = set()
        frame_index    = 0
        db_rows_written = 0
        _resolution_written = False  # write stream resolution once from first valid frame

        async for message_id, manifest in source.manifests():
            if manifest.get("status") == "offline":
                log.debug(
                    "Skipping offline window  batch=%s  camera=%s",
                    manifest.get("batch_number"), camera_id,
                )
                await source.ack(message_id)
                continue

            for frame_entry in manifest.get("frames", []):
                capture_ts_ms = int(frame_entry[0])
                s3_key        = frame_entry[1]

                frame = _fetch_s3_frame(s3_client, s3_bucket, s3_key)
                if frame is None:
                    continue

                if not _resolution_written:
                    _h, _w = frame.shape[:2]
                    if _w > 0 and _h > 0:
                        await persistence.write_stream_resolution(camera_id, _w, _h)
                    else:
                        log.warning(
                            "Could not read stream resolution from source "
                            "(width=%d height=%d) — stream_width/height not updated",
                            _w, _h,
                        )
                    _resolution_written = True

                detections = detect(self.yolo_model, frame)
                tracks     = update(tracker, detections)
                _project_tracks(tracks, projector)
                enriched   = manager.process_frame(frame, tracks)

                log.debug(
                    "Frame %4d  detections=%d  tracks=%d  confirmed=%d  pending=%d",
                    frame_index, len(detections), len(tracks),
                    sum(1 for t in enriched if t["local_id"] is not None),
                    sum(1 for t in enriched if t["local_id"] is None),
                )

                rows = await self._run_frame_detections(enriched, capture_ts_ms, persistence, projector)
                db_rows_written += rows

                frame_b64, scale = _encode_frame(frame)
                display_tracks = (
                    [{**t, "bbox": [c * scale for c in t["bbox"]]} for t in enriched]
                    if scale != 1.0 else enriched
                )

                new_entries = [t["track_id"] for t in enriched if t["track_id"] not in seen_ids]
                seen_ids.update(t["track_id"] for t in enriched)
                if new_entries:
                    log.info("Frame %4d  new track_ids=%s", frame_index, new_entries)

                if live_pub:
                    live_pub.publish(s3_key or "", capture_ts_ms, display_tracks)

                yield FrameResult(
                    frame_index=frame_index,
                    frame_b64=frame_b64,
                    tracks=display_tracks,
                    new_entries=new_entries,
                )
                frame_index += 1

            # Strict batch-close order: tracking writes → centroids → batch_complete → XACK.
            await self._flush_centroids(
                manager, persistence, manifest.get("batch_number", 0)
            )
            await self._publish_batch_complete(
                redis_client=source.redis_client,
                batch_number=manifest.get("batch_number", 0),
                window_start_ms=manifest.get("window_start_ms", 0),
                window_end_ms=manifest.get("window_end_ms", 0),
            )
            await source.ack(message_id)

        log.info(
            "Stream finished (IEP1)  camera=%s  frames=%d  db_rows=%d",
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
        store_id=os.environ.get("STORE_ID", "00000000-0000-0000-0000-000000000001"),
        camera_id="cam0",
        database_url=os.environ.get("DATABASE_URL", ""),
        camera_config_id=os.environ.get("CAMERA_CONFIG_ID"),
    )

    async def _run():
        runtime = IEP2Runtime(settings)
        async with runtime.run(sys.argv[1]) as stream:
            async for result in stream:
                print(f"frame={result.frame_index} tracks={len(result.tracks)}")

    asyncio.run(_run())
