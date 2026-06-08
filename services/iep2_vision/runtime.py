"""IEP2 pipeline owner — models, orchestration, stream interface.

Usage (daemon — production):
    from runtime import run_daemon, Settings
    asyncio.run(run_daemon(Settings()))

Usage (video file — dev):
    async with runtime.run(video_path) as stream:
        async for result in stream: ...

Usage (live from IEP1 — legacy):
    async with runtime.run_from_iep1() as stream:
        async for result in stream: ...
"""
import asyncio
import base64
import io
import logging
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Tuple

log = logging.getLogger("iep2.runtime")

import cv2
import numpy as np
from PIL import Image

try:
    from .detector.detector import YoloClient
    from .reid.reid import ReidClient
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
    from detector.detector import YoloClient
    from reid.reid import ReidClient
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

    Called after BoTSORT update, before identity manager, so the manager and
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
        """Initialise service clients. No models loaded locally — both delegated via ZMQ."""
        self.settings = settings
        self.yolo_client  = YoloClient(camera_id=settings.camera_id)
        self.reid_client = ReidClient(camera_id=settings.camera_id)
        log.info(
            "IEP2Runtime initialised  camera=%s  "
            "(YOLO→yolo-service, ReID→reid-service via ZMQ)",
            settings.camera_id,
        )

    @asynccontextmanager
    async def run(self, video_path: str, start_ms: int = 0):
        """Async context manager that yields the frame stream from a video file."""
        await self.yolo_client.start()
        await self.reid_client.start()
        try:
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
        finally:
            await self.yolo_client.close()
            await self.reid_client.close()

    @asynccontextmanager
    async def run_from_iep1(self):
        """Async context manager that yields the frame stream from IEP1 via Redis + S3."""
        await self.yolo_client.start()
        await self.reid_client.start()
        try:
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
        finally:
            await self.yolo_client.close()
            await self.reid_client.close()

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
        frame_count: int = 0,
    ) -> None:
        """XADD one batch_complete event to stream:iep2:batch_complete with MAXLEN.

        Called after centroid flush and before XACK (R10 M2-S4).
        A failed XADD is logged but does not prevent XACK.
        """
        fields = {
            "camera_id":       self.settings.camera_id,
            "store_id":        self.settings.store_id,
            "batch_number":    str(batch_number),
            "window_start_ms": str(window_start_ms),
            "window_end_ms":   str(window_end_ms),
            "frame_count":     str(frame_count),
        }
        try:
            await redis_client.xadd(
                "stream:iep2:batch_complete", fields, maxlen=500, approximate=True
            )
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
                    bbox_x1=x1,
                    bbox_y1=y1,
                    bbox_x2=x2,
                    bbox_y2=y2,
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
        manager        = LocalIdentityManager(reid_client=self.reid_client)
        seen_ids: set  = set()
        frame_index    = 0
        db_rows_written = 0

        for _capture_ts_ms, _s3_key, frame in source:
            detections = await self.yolo_client.detect(frame, _capture_ts_ms)
            tracks     = update(tracker, detections, frame)
            _project_tracks(tracks, projector)
            enriched, _, __ = await manager.process_frame(frame, tracks, timestamp_ms=_capture_ts_ms)

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
        manager        = LocalIdentityManager(reid_client=self.reid_client)
        seen_ids: set  = set()
        frame_index    = 0
        db_rows_written = 0
        _resolution_written = False  # write stream resolution once from first valid frame

        async def _load_and_detect_s3(mfst: dict) -> tuple[list, list, list, list]:
            """Fetch frames from S3/tmpfs and run detect_batch for one manifest.

            Returns (frames, timestamps_ms, s3_keys, detections_per_frame).
            Unreadable frames are excluded from all four lists.
            """
            raw_frames, raw_ts, raw_keys = [], [], []
            for entry in mfst.get("frames", []):
                ts  = int(entry[0])
                key = entry[1]
                f   = _fetch_s3_frame(s3_client, s3_bucket, key)
                if f is not None:
                    raw_frames.append(f)
                    raw_ts.append(ts)
                    raw_keys.append(key)
            if not raw_frames:
                return [], [], [], []
            dets = await self.yolo_client.detect_batch(raw_frames, raw_ts)
            return raw_frames, raw_ts, raw_keys, dets

        async for message_id, manifest in source.manifests():
            if manifest.get("status") == "offline":
                log.debug(
                    "Skipping offline window  batch=%s  camera=%s",
                    manifest.get("batch_number"), camera_id,
                )
                await source.ack(message_id)
                continue

            # Send entire batch to YOLO at once — measure wall time.
            _t_yolo_s3 = time.monotonic()
            batch_frames, batch_ts, batch_keys, batch_detections = await _load_and_detect_s3(manifest)
            yolo_ms_s3 = (time.monotonic() - _t_yolo_s3) * 1000

            # Write stream resolution from the first valid frame of the run.
            if not _resolution_written and batch_frames:
                _h, _w = batch_frames[0].shape[:2]
                if _w > 0 and _h > 0:
                    await persistence.write_stream_resolution(camera_id, _w, _h)
                else:
                    log.warning(
                        "Could not read stream resolution (width=%d height=%d) — skipping",
                        _w, _h,
                    )
                _resolution_written = True

            # Sequential tracker/reid/DB pass over the pre-detected frames.
            reid_crops_s3   = 0
            reid_batches_s3 = 0
            tracker_ms_s3    = 0.0
            for frame, capture_ts_ms, s3_key, detections in zip(
                batch_frames, batch_ts, batch_keys, batch_detections
            ):
                _t_frame_s3 = time.monotonic()
                tracks   = update(tracker, detections, frame)
                _project_tracks(tracks, projector)
                enriched, _crops_s3, _batches_s3 = await manager.process_frame(frame, tracks, timestamp_ms=capture_ts_ms)
                tracker_ms_s3    += (time.monotonic() - _t_frame_s3) * 1000
                reid_crops_s3   += _crops_s3
                reid_batches_s3 += _batches_s3

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

            _avg_tracker_s3 = (tracker_ms_s3 / len(batch_frames)) if batch_frames else 0.0
            log.info(
                "Batch stats  camera=%s  batch=%s  frames=%d"
                "  yolo_ms=%.0f  tracker_ms=%.0f  reid_recalls=%d  batch_reid_recalls=%d"
                "  avg_tracker_ms_per_frame=%.1f",
                camera_id, manifest.get("batch_number"), len(batch_frames),
                yolo_ms_s3, tracker_ms_s3, reid_crops_s3, reid_batches_s3, _avg_tracker_s3,
            )

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
# Daemon mode — Settings (pydantic-settings, env vars only, no CLI args).
# ---------------------------------------------------------------------------

def _make_settings_class():
    try:
        from pydantic_settings import BaseSettings
        from pydantic import Field as _Field

        class Settings(BaseSettings):
            camera_id:           str   = _Field(...)
            camera_config_id:    str   = _Field(default="")
            store_id:            str   = _Field(...)
            window_seconds:      float = _Field(..., gt=0)
            local_redis_url:     str   = _Field(...)
            server_redis_url:    str   = _Field(...)
            database_url_server: str   = _Field(...)
            yolo_input_sock:     str   = _Field(default="ipc:///tmp/sockets/yolo_input.sock")
            reid_input_sock:    str   = _Field(default="ipc:///tmp/sockets/reid_input.sock")
            tmpfs_frame_root:    str   = _Field(default="/dev/shm/frames")
            target_fps:          float = _Field(default=5.0, gt=0)
            health_sock:         str   = _Field(default="")
            # R7: CA cert for TLS verification of server Redis (shares CA with gRPC)
            redis_ca_cert_path:  str   = _Field(default="/etc/retailvision/certs/ca.crt")
            # Live preview: publish per-frame detections to stream:iep2:live:{camera_id}.
            # live_embed_frame base64-embeds the JPEG (dev — no S3). Both default off;
            # enabled in dev via LIVE_STREAM_ENABLED / LIVE_EMBED_FRAME env vars.
            live_stream_enabled: bool  = _Field(default=False)
            live_embed_frame:    bool  = _Field(default=False)

            class Config:
                env_file = ".env"
                extra    = "ignore"

        return Settings
    except ImportError:
        return None


_Settings = _make_settings_class()
if _Settings is not None:
    Settings = _Settings  # exported symbol


def _read_frame_from_tmpfs(path: str):
    """Read a JPEG from the IEP1 tmpfs path. Returns BGR ndarray or None."""
    import cv2 as _cv2
    frame = _cv2.imread(path)
    if frame is None:
        log.warning("Failed to read frame from tmpfs path=%s", path)
    return frame


async def _cleanup_frames(manifest: dict) -> None:
    """R12 (M2-S4): delete tmpfs frame files after manifest is fully processed."""
    for entry in manifest.get("frames", []):
        path = entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else None
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as exc:
                log.warning("tmpfs cleanup failed path=%s: %s", path, exc)


async def _run_health_service(settings) -> None:
    """R11 (M2-S4): gRPC health service on per-camera unix socket.

    Reports NOT_SERVING if YOLO or ReID TCP health endpoints are unreachable.
    """
    try:
        import grpc
        import grpc.aio
        from grpc_health.v1 import health, health_pb2, health_pb2_grpc

        sock = settings.health_sock or (
            f"unix:///tmp/sockets/iep2_health_{settings.camera_id}.sock"
        )
        health_servicer = health.HealthServicer()
        server = grpc.aio.server()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
        server.add_insecure_port(sock)
        await server.start()
        health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
        log.info("IEP2 health service  camera=%s  sock=%s", settings.camera_id, sock)

        yolo_addr  = os.environ.get("YOLO_HEALTH_TCP_ADDR",  "yolo-service:50052")
        reid_addr = os.environ.get("REID_HEALTH_TCP_ADDR", "reid-service:50053")

        while True:
            await asyncio.sleep(10)
            yolo_ok  = await _grpc_health_ping(yolo_addr)
            reid_ok = await _grpc_health_ping(reid_addr)
            status = (
                health_pb2.HealthCheckResponse.SERVING
                if yolo_ok and reid_ok
                else health_pb2.HealthCheckResponse.NOT_SERVING
            )
            health_servicer.set("", status)
            if not (yolo_ok and reid_ok):
                log.warning(
                    "Health degraded  camera=%s  yolo=%s  reid=%s",
                    settings.camera_id, yolo_ok, reid_ok,
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("Health service failed  camera=%s: %s", settings.camera_id, exc)


async def _watch_reload_signals(
    camera_config_id: str,
    projector: "FloorProjector",
    pool,
    server_redis,
) -> None:
    """R5 (M5-S1): Subscribe to EEP homography reload signals via server Redis pub/sub.

    EEP publishes `iep2:reload:{camera_config_id}` → 'homography' when a new
    calibration is written. IEP2 reloads the floor projector without restarting.
    Runs as a background task alongside the main manifest consumer loop.
    """
    import uuid as _uuid
    channel = f"iep2:reload:{camera_config_id}"
    while True:
        try:
            pubsub = server_redis.pubsub()
            await pubsub.subscribe(channel)
            log.info("Subscribed to reload channel  channel=%s", channel)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    cal_type = (message["data"] or b"").decode("utf-8", errors="ignore")
                    log.info(
                        "Calibration reload signal received  type=%s  camera_config_id=%s",
                        cal_type, camera_config_id,
                    )
                    try:
                        await projector.load(pool, _uuid.UUID(camera_config_id))
                        log.info("Calibration reloaded  type=%s  camera_config_id=%s", cal_type, camera_config_id)
                    except Exception as exc:
                        log.error(
                            "Calibration reload failed  camera_config_id=%s: %s",
                            camera_config_id, exc,
                        )
        except asyncio.CancelledError:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
            raise
        except Exception as exc:
            log.warning("Reload watcher error  channel=%s: %s — retrying in 5s", channel, exc)
            await asyncio.sleep(5)


async def _grpc_health_ping(addr: str) -> bool:
    """Return True if the gRPC health endpoint reports SERVING."""
    try:
        import grpc
        import grpc.aio
        from grpc_health.v1 import health_pb2, health_pb2_grpc
        async with grpc.aio.insecure_channel(addr) as ch:
            stub = health_pb2_grpc.HealthStub(ch)
            resp = await stub.Check(
                health_pb2.HealthCheckRequest(service=""), timeout=2.0
            )
            return resp.status == health_pb2.HealthCheckResponse.SERVING
    except Exception:
        return False


async def run_daemon(settings) -> None:
    """Long-running IEP2 daemon (R1 M2-S4).

    Reads IEP1 manifests from local Redis, processes frames from tmpfs,
    writes tracking_history to cloud DB, publishes batch_complete to server Redis.
    BoTSORT and LocalIdentityManager state persist across all batch boundaries.
    """
    import asyncio
    import redis as _sync_redis
    import redis.asyncio as aioredis

    try:
        from .detector.detector import YoloClient
        from .reid.reid import ReidClient
        from .tracker.tracker import create_tracker, update
        from .identity.manager import LocalIdentityManager
        from .persistence.postgres import PostgresPersistence
        from .projection.projector import FloorProjector
        from .ingest.redis_source import RedisStreamFrameSource
    except ImportError:
        _root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _root)
        from detector.detector import YoloClient
        from reid.reid import ReidClient
        from tracker.tracker import create_tracker, update
        from identity.manager import LocalIdentityManager
        from persistence.postgres import PostgresPersistence
        from projection.projector import FloorProjector
        from ingest.redis_source import RedisStreamFrameSource

    log.info(
        "IEP2 daemon starting  camera=%s  store=%s  local_redis=%s  server_redis=%s",
        settings.camera_id, settings.store_id,
        settings.local_redis_url, settings.server_redis_url,
    )

    # ── Connections ───────────────────────────────────────────────────────────
    local_redis = aioredis.Redis.from_url(settings.local_redis_url, decode_responses=False)

    # R7: server Redis connection uses TLS (rediss:// scheme required in SERVER_REDIS_URL)
    _server_redis_kwargs = dict(decode_responses=False, socket_connect_timeout=5, socket_timeout=10, retry_on_timeout=True)
    if settings.server_redis_url.startswith("rediss://"):
        _server_redis_kwargs["ssl_ca_certs"] = settings.redis_ca_cert_path
    server_redis = aioredis.Redis.from_url(settings.server_redis_url, **_server_redis_kwargs)

    # Sync Redis client for LocalIdentityManager counter persistence
    sync_redis = _sync_redis.Redis.from_url(settings.local_redis_url, decode_responses=True)

    async with PostgresPersistence(
        database_url=settings.database_url_server,
        store_id=settings.store_id,
        camera_id=settings.camera_id,
    ) as persistence:

        # ── ML clients ────────────────────────────────────────────────────────
        yolo_client  = YoloClient(camera_id=settings.camera_id)
        reid_client = ReidClient(camera_id=settings.camera_id)
        await yolo_client.start()
        await reid_client.start()

        # ── Pipeline components ───────────────────────────────────────────────
        tracker  = create_tracker()
        manager  = LocalIdentityManager(
            reid_client=reid_client,
            camera_id=settings.camera_id,
            redis_local=sync_redis,
        )
        projector = FloorProjector()
        if settings.camera_config_id:
            await projector.load(persistence.pool, uuid.UUID(settings.camera_config_id))

        # ── Health service background task ────────────────────────────────────
        health_task = asyncio.create_task(_run_health_service(settings))

        # ── R5: homography reload subscription (server Redis pub/sub) ─────────
        reload_task = asyncio.create_task(
            _watch_reload_signals(settings.camera_config_id, projector, persistence.pool, server_redis),
            name=f"reload-watch-{settings.camera_id}",
        ) if settings.camera_config_id else None

        # ── Live preview publisher (server Redis → Live Bridge) ───────────────
        live_pub = LivePublisher(
            camera_id=settings.camera_id,
            redis_url=settings.server_redis_url,
            enabled=bool(settings.live_stream_enabled or settings.live_embed_frame),
            embed_frame=bool(settings.live_embed_frame),
        )

        # ── Manifest consumer (local Redis, IEP1 stream) ──────────────────────
        consumer = RedisStreamFrameSource(
            camera_id=settings.camera_id,
            redis_url=settings.local_redis_url,
            s3_client=None,  # frames come from tmpfs, not S3
        )
        await consumer.connect()

        try:
            log.info("IEP2 daemon SERVING  camera=%s", settings.camera_id)

            async def _load_and_detect(mfst: dict) -> tuple[list, list, list]:
                """Load frames from tmpfs and run detect_batch for one manifest.

                Returns (frames, timestamps_ms, detections_per_frame).
                Skipped (unreadable) frames are excluded from all three lists.
                """
                raw_frames, raw_ts = [], []
                for entry in mfst.get("frames", []):
                    f = _read_frame_from_tmpfs(entry[1])
                    if f is not None:
                        raw_frames.append(f)
                        raw_ts.append(int(entry[0]))
                if not raw_frames:
                    return [], [], []
                dets = await yolo_client.detect_batch(raw_frames, raw_ts)
                return raw_frames, raw_ts, dets

            # Pipeline parallelism: while we run tracker/reid/DB on batch N,
            # YOLO inference for batch N+1 runs concurrently as a background task.
            yolo_task: asyncio.Task | None = None

            async for message_id, manifest in consumer.manifests():
                if manifest.get("status") == "offline":
                    await consumer.ack(message_id)
                    continue

                # Launch YOLO for this manifest immediately so it overlaps with
                # any remaining tracker work from the previous iteration.
                this_yolo_task = asyncio.create_task(
                    _load_and_detect(manifest),
                    name=f"yolo-{settings.camera_id}-{manifest.get('batch_number', 0)}",
                )

                # If there was a previous YOLO task still running, await it now.
                # (First iteration: yolo_task is None, skip.)
                if yolo_task is not None:
                    # yolo_task belongs to the *previous* manifest — it should already
                    # be done; awaiting it here is just a safety drain.
                    try:
                        await yolo_task
                    except Exception as exc:
                        log.warning("Previous YOLO task error: %s", exc)

                # Await current batch YOLO results — measure wall time.
                _t_yolo_start = time.monotonic()
                batch_frames_data, batch_ts, batch_detections = await this_yolo_task
                yolo_ms = (time.monotonic() - _t_yolo_start) * 1000
                yolo_task = None

                # ── Sequential tracker/reid/DB pass ──────────────────────────
                frame_count    = 0
                reid_crops    = 0
                reid_batches  = 0
                tracker_ms     = 0.0
                for frame, capture_ts_ms, detections in zip(batch_frames_data, batch_ts, batch_detections):
                    _t_frame = time.monotonic()
                    tracks   = update(tracker, detections, frame)
                    _project_tracks(tracks, projector)
                    enriched, _crops, _batches = await manager.process_frame(
                        frame, tracks, timestamp_ms=capture_ts_ms
                    )
                    tracker_ms    += (time.monotonic() - _t_frame) * 1000
                    reid_crops   += _crops
                    reid_batches += _batches

                    live_pub.publish_frame(frame, capture_ts_ms, enriched)

                    for track in enriched:
                        if track["local_id"] is None:
                            continue
                        x1, y1, x2, y2 = [int(c) for c in track["bbox"]]
                        floor_x = track.get("floor_x")
                        floor_y = track.get("floor_y")
                        zone_id = (
                            projector.zone_of(floor_x, floor_y)
                            if floor_x is not None and floor_y is not None
                            else None
                        )
                        await persistence.insert_detection(
                            local_id=uuid.UUID(int=track["local_id"]),
                            timestamp_ms=capture_ts_ms,
                            bbox_confidence=float(track["confidence"]),
                            bbox_area=(x2 - x1) * (y2 - y1),
                            floor_x=floor_x,
                            floor_y=floor_y,
                            zone_id=zone_id,
                            bbox_x1=x1,
                            bbox_y1=y1,
                            bbox_x2=x2,
                            bbox_y2=y2,
                        )
                    frame_count += 1

                # ── Strict batch-close order: centroids → batch_complete → XACK → cleanup ──
                await _flush_centroids_daemon(
                    manager, persistence,
                    settings.camera_id, settings.store_id,
                    manifest.get("batch_number", 0),
                )

                await server_redis.xadd(
                    "stream:iep2:batch_complete",
                    {
                        "camera_id":       settings.camera_id,
                        "store_id":        settings.store_id,
                        "batch_number":    str(manifest.get("batch_number", 0)),
                        "window_start_ms": str(manifest.get("window_start_ms", 0)),
                        "window_end_ms":   str(manifest.get("window_end_ms", 0)),
                        "frame_count":     str(frame_count),
                    },
                    maxlen=500,
                    approximate=True,
                )
                await consumer.ack(message_id)
                await _cleanup_frames(manifest)

                avg_tracker = (tracker_ms / frame_count) if frame_count else 0.0
                log.info(
                    "Batch stats  camera=%s  batch=%s  frames=%d"
                    "  yolo_ms=%.0f  tracker_ms=%.0f  reid_recalls=%d  batch_reid_recalls=%d"
                    "  avg_tracker_ms_per_frame=%.1f",
                    settings.camera_id, manifest.get("batch_number"), frame_count,
                    yolo_ms, tracker_ms, reid_crops, reid_batches, avg_tracker,
                )

        except asyncio.CancelledError:
            log.info("IEP2 daemon cancelled  camera=%s", settings.camera_id)
            raise
        finally:
            for task in (health_task, reload_task):
                if task is not None:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            await yolo_client.close()
            await reid_client.close()
            await consumer.close()
            await local_redis.aclose()
            await server_redis.aclose()
            sync_redis.close()


async def _flush_centroids_daemon(
    manager,
    persistence,
    camera_id: str,
    store_id: str,
    batch_number: int,
) -> None:
    """UPSERT active centroids at daemon batch-close (centroids → batch_complete → XACK order)."""
    active = manager.get_active_centroids()
    if not active:
        return
    records = [
        {
            "local_id":         str(uuid.UUID(int=lid)),
            "camera_id":        camera_id,
            "store_id":         store_id,
            "centroid":         arr.astype("float32").tobytes(),
            "updated_at_batch": batch_number,
        }
        for lid, arr in active.items()
    ]
    await persistence.upsert_local_centroids(records)


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
        database_url_server=os.environ.get("DATABASE_URL_SERVER", ""),
        window_seconds=float(os.environ.get("WINDOW_SECONDS", "60")),
        camera_config_id=os.environ.get("CAMERA_CONFIG_ID"),
    )

    async def _run():
        runtime = IEP2Runtime(settings)
        async with runtime.run(sys.argv[1]) as stream:
            async for result in stream:
                print(f"frame={result.frame_index} tracks={len(result.tracks)}")

    asyncio.run(_run())
