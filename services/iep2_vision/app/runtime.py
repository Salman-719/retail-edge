"""Per-camera runtime assembly: wires M2 (vision) + M3 (identity) + M4
(persistence, ingest, events) and drives the batch loop.

A separate runtime/process runs per camera. M6's orchestrator launches N of these
against N videos with a shared ``start_epoch_ms`` so their timelines align.

Detector/tracker/embedder are built from config by default but can be injected
(dependency injection) for tests and the CPU/no-weights path. The events emitter
is likewise injectable so e2e tests can capture emissions without Redis.
"""

from __future__ import annotations

from services.iep2_vision.app.calibration import load_calibration
from services.iep2_vision.app.events import BatchEventEmitter
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from services.iep2_vision.app.ingest.batcher import Batcher
from services.iep2_vision.app.ingest.video_source import VideoFrameSource
from services.iep2_vision.app.persistence.postgres import PostgresPersistence
from services.iep2_vision.app.recovery import reconstruct_lost_pool
from services.iep2_vision.app.vision.detector import create_detector
from services.iep2_vision.app.vision.pipeline import VisionPipeline
from services.iep2_vision.app.vision.projection import FloorProjector
from services.iep2_vision.app.vision.reid import create_reid_model
from services.iep2_vision.app.vision.tracker import create_tracker


class Iep2Runtime:
    def __init__(self, store_id, camera_id, settings):
        self._store, self._cam, self._s = store_id, camera_id, settings

    async def setup(self, calibration_row, *, detector=None, tracker=None, embedder=None,
                    persistence=None, events=None, warm_restart: bool = True) -> None:
        H, zones, bounds = load_calibration(calibration_row)

        detector = detector or create_detector(
            self._s.detector_backend, model_name=self._s.detector_model,
            confidence=self._s.detector_confidence, nms_iou=self._s.detector_nms_iou,
            device=self._s.device,
        )
        tracker = tracker or create_tracker(
            self._s.tracker_backend, min_hits=self._s.bytetrack_min_hits,
            max_age=self._s.bytetrack_max_age, track_thresh=self._s.bytetrack_track_thresh,
            match_thresh=self._s.bytetrack_match_thresh,
        )
        self._embedder = embedder or create_reid_model(
            self._s.reid_backend, model_name=self._s.reid_model, weights=None, device=self._s.device,
        )
        # the model's actual dim overrides config (spec mandate)
        self._s.embedding_dim = self._embedder.embedding_dim

        projector = FloorProjector(H, zones, bounds)
        self._pipeline = VisionPipeline(detector, tracker, projector, self._s)
        self._db = persistence or PostgresPersistence(self._s)
        self._manager = LocalIdentityManager(self._cam, self._embedder, self._db, self._s)
        self._events = events or BatchEventEmitter()

        if warm_restart:
            self._manager.pools.lost = await reconstruct_lost_pool(self._cam, 0, self._s)

    async def run(self, video_path: str, start_epoch_ms: int) -> None:
        source = VideoFrameSource(video_path, self._s.sample_rate_fps, start_epoch_ms)
        batcher = Batcher(source, self._s.batch_window_seconds, self._s.sample_rate_fps)
        for batch_number, frames in batcher:
            window_start = frames[0].timestamp_ms
            window_end = frames[-1].timestamp_ms
            for sf in frames:
                frame_dets, tracker_out, _ = self._pipeline.process_frame(sf.frame)
                await self._manager.process_frame(sf.frame, frame_dets, tracker_out, sf.timestamp_ms)
                await self._db.maybe_flush()
            await self._db.maybe_flush(force=True)  # final flush for the batch
            self._manager.on_batch_boundary(batch_number)
            await self._events.emit(self._store, self._cam, batch_number, window_start, window_end)
