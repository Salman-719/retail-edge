"""Per-camera runtime assembly: wires M2 (vision) + M3 (identity) + M4
(persistence, ingest, events) and drives the batch loop.

A separate runtime/process runs per camera. M6's orchestrator launches N of these
against N videos with a shared ``start_epoch_ms`` so their timelines align.

Detector/tracker/embedder are built from config by default but can be injected
(dependency injection) for tests and the CPU/no-weights path. The events emitter
is likewise injectable so e2e tests can capture emissions without Redis.
"""

from __future__ import annotations

from time import perf_counter

from services.iep2_vision.app import metrics
from services.iep2_vision.app.calibration import load_calibration
from services.iep2_vision.app.events import BatchEventEmitter
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from services.iep2_vision.app.ingest.batcher import Batcher
from services.iep2_vision.app.ingest.video_source import VideoFrameSource
from services.iep2_vision.app.persistence.postgres import PostgresPersistence
from services.iep2_vision.app.persistence.eep_http import EepHttpPersistence
from services.iep2_vision.app.recovery import reconstruct_lost_pool
from services.iep2_vision.app.vision.detector import create_detector
from services.iep2_vision.app.vision.pipeline import VisionPipeline
from services.iep2_vision.app.vision.projection import FloorProjector
from services.iep2_vision.app.vision.reid import create_reid_model
from services.iep2_vision.app.vision.tracker import create_tracker


class Iep2Runtime:
    def __init__(self, store_id, camera_id, settings):
        self._store, self._cam, self._s = store_id, camera_id, settings

    async def setup(
        self,
        calibration_row,
        *,
        detector=None,
        tracker=None,
        embedder=None,
        persistence=None,
        events=None,
        warm_restart: bool = True,
        current_batch: int = 0,
    ) -> None:
        H, zones, bounds = load_calibration(calibration_row)

        detector = detector or create_detector(
            self._s.detector_backend, model_name=self._s.detector_model,
            confidence=self._s.detector_confidence, nms_iou=self._s.detector_nms_iou,
            device=self._s.device, weights=self._s.detector_weights,
            allow_fallback=self._s.detector_allow_fallback,
            fallback_model=self._s.detector_fallback_model,
            yolox_input_size=(self._s.yolox_input_height, self._s.yolox_input_width),
        )
        def tracker_factory():
            return create_tracker(
                self._s.tracker_backend, min_hits=self._s.bytetrack_min_hits,
                max_age=self._s.bytetrack_max_age, track_thresh=self._s.bytetrack_track_thresh,
                match_thresh=self._s.bytetrack_match_thresh,
            )

        tracker_factory_for_pipeline = None if tracker is not None else tracker_factory
        tracker = tracker or tracker_factory()
        self._embedder = embedder or create_reid_model(
            self._s.reid_backend, model_name=self._s.reid_model, weights=None, device=self._s.device,
        )
        self.embedding_dim = self._embedder.embedding_dim

        projector = FloorProjector(H, zones, bounds)
        self._pipeline = VisionPipeline(detector, tracker, projector, self._s, tracker_factory_for_pipeline)
        if persistence is not None:
            self._db = persistence
        elif getattr(self._s, "EEP_BASE_URL", None):
            self._db = EepHttpPersistence(str(self._store), self._s)
        else:
            self._db = PostgresPersistence(self._s)
        self._manager = LocalIdentityManager(self._cam, self._embedder, self._db, self._s)
        # When using EepHttpPersistence, EEP publishes batch_complete to Redis
        # after writing the batch. BatchEventEmitter is only used for direct-DB mode.
        self._events = events or (
            BatchEventEmitter() if not isinstance(self._db, EepHttpPersistence) else _NoOpEmitter()
        )

        if warm_restart:
            self._manager.pools.lost = await reconstruct_lost_pool(self._cam, current_batch, self._s)

    def reset_tracker(self) -> None:
        self._pipeline.reset_tracker()

    async def process_sampled_frame(self, frame, timestamp_ms: int) -> None:
        t0 = perf_counter()
        frame_dets, tracker_out, _ = self._pipeline.process_frame(frame)
        await self._manager.process_frame(frame, frame_dets, tracker_out, timestamp_ms)
        await self._db.maybe_flush()
        metrics.frame_latency.labels(self._cam).observe(perf_counter() - t0)
        metrics.detections_per_frame.labels(self._cam).observe(len(frame_dets))
        for d in frame_dets:
            metrics.detection_confidence.labels(self._cam).observe(d.confidence)

    async def flush_batch(self, batch_number: int, window_start_ms: int, window_end_ms: int) -> None:
        await self._db.maybe_flush(force=True)
        self._manager.on_batch_boundary(batch_number)
        metrics.active_tracks.labels(self._cam).set(len(self._manager.pools.active))
        metrics.lost_pool_size.labels(self._cam).set(len(self._manager.pools.lost))
        await self._events.emit(self._store, self._cam, batch_number, window_start_ms, window_end_ms)

    async def run(self, video_path: str, start_epoch_ms: int) -> None:
        source = VideoFrameSource(video_path, self._s.sample_rate_fps, start_epoch_ms)
        batcher = Batcher(source, self._s.batch_window_seconds, self._s.sample_rate_fps)
        for batch_number, frames in batcher:
            window_start = frames[0].timestamp_ms
            if len(frames) > 1:
                sample_period_ms = max(1, frames[-1].timestamp_ms - frames[-2].timestamp_ms)
            else:
                sample_period_ms = max(1, int(round(1000.0 / self._s.sample_rate_fps)))
            window_end = frames[-1].timestamp_ms + sample_period_ms
            for sf in frames:
                await self.process_sampled_frame(sf.frame, sf.timestamp_ms)
            await self.flush_batch(batch_number, window_start, window_end)
