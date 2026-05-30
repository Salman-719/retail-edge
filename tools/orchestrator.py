"""Lightweight orchestrator -- a stand-in for EEP, sufficient to run and demo the
full IEP1 -> IEP2 -> IEP3 subsystem.

Two modes:

* ``run_via_iep1`` (**default**) -- the real chain. Launches one IEP1 ingestion
  worker per camera (video -> JPEG frames in S3 + window manifests on
  ``stream:iep1:{cam}``) and one IEP2 ``run_from_iep1`` consumer per camera, with
  IEP3 reconciliation in the same process. IEP2 emits ``batch_complete`` to the
  in-process coordinator adapter. Requires Redis + S3 (MinIO) + Postgres.

* ``run`` (``--direct`` fallback) -- the original in-process direct-video path:
  IEP2 reads the video file directly (no IEP1, no S3/Redis frame transport),
  emitting to the same coordinator. Kept for weight-free local runs and the
  existing direct e2e.

For production this is replaced by EEP; the orchestrator stays minimal -- its only
job is to exercise the full chain for tests and the demo.
"""

from __future__ import annotations

import asyncio

from common.config import get_settings
from common.utils.time import now_ms
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep3_reconciliation.app.coordinator import BatchCoordinator
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository


class RunPlan:
    """Describes one demo/test run: store, cameras, and their videos."""

    def __init__(self, store_id, cameras: dict[str, str], frame_px: dict[str, int]):
        self.store_id = store_id
        self.cameras = cameras  # camera_id -> video_path
        self.frame_px = frame_px  # camera_id -> frame pixel area


class _InProcessEmitter:
    """Adapts IEP2's BatchEventEmitter interface onto the IEP3 coordinator,
    without Redis. ``emit`` drives ``coordinator.note`` directly."""

    def __init__(self, coordinator: BatchCoordinator):
        self._coord = coordinator

    async def emit(self, store_id, camera_id, batch_number, window_start_ms, window_end_ms) -> None:
        await self._coord.note(batch_number, camera_id, (window_start_ms, window_end_ms))

    async def close(self) -> None:  # parity with BatchEventEmitter
        pass


async def run(plan: RunPlan, calibrations: dict, *, overrides: dict | None = None,
              settings=None, start_ms: int | None = None) -> None:
    """Run the full IEP2->IEP3 chain for ``plan``.

    ``calibrations``: camera_id -> calibration row (CameraCalibration / duck type).
    ``overrides``: camera_id -> kwargs forwarded to ``Iep2Runtime.setup`` (detector/
    tracker/embedder/persistence/warm_restart) for tests and the CPU path.
    """
    settings = settings or get_settings()
    start_ms = start_ms or now_ms()
    overrides = overrides or {}

    repo = Iep3Repository(settings)
    reconciler = Reconciler(plan.store_id, repo, settings, plan.frame_px)
    coordinator = BatchCoordinator(expected_cameras=set(plan.cameras), on_ready=reconciler.process_batch)
    emitter = _InProcessEmitter(coordinator)

    async def run_camera(cam_id: str, video: str) -> None:
        rt = Iep2Runtime(plan.store_id, cam_id, settings)
        setup_kwargs = dict(events=emitter, warm_restart=False)
        setup_kwargs.update(overrides.get(cam_id, {}))
        await rt.setup(calibrations[cam_id], **setup_kwargs)
        await rt.run(video, start_ms)

    await asyncio.gather(*[run_camera(c, v) for c, v in plan.cameras.items()])
    # cameras finished; reconcile any batches not reported by every camera (uneven
    # video lengths / trailing partial batch) so nothing is left unprocessed.
    await coordinator.drain()


async def run_via_iep1(plan: RunPlan, calibrations: dict, *, overrides: dict | None = None,
                       settings=None, start_ms: int | None = None,
                       s3_client=None, redis_client=None) -> None:
    """Run the real IEP1 -> IEP2 -> IEP3 chain for ``plan`` (default path).

    For each camera: an IEP1 worker ingests the video to S3 + a manifest stream,
    then an IEP2 ``run_from_iep1`` consumer reads those manifests, fetches frames
    from S3, and feeds the identity pipeline; IEP3 reconciles via the in-process
    coordinator. IEP1 runs to completion first (finite video files), then IEP2
    drains the per-camera streams -- a sentinel stops each consumer once its
    camera's manifests are exhausted. Requires Redis + S3 + Postgres.

    ``s3_client`` is used only to ensure the bucket exists (the caller may pass its
    own handle for inspection); ``redis_client`` is accepted for API symmetry. The
    per-camera workers always build their OWN clients (see below) to avoid sharing
    one client across concurrent tasks.
    """
    from common.s3 import S3Client
    from services.iep1_ingestion.app.runtime import Iep1Runtime
    from services.iep1_ingestion.app.source.video_source import VideoFileSource
    from services.iep2_vision.app.ingest.redis_stream_source import RedisStreamFrameSource

    settings = settings or get_settings()
    start_ms = start_ms or now_ms()
    overrides = overrides or {}

    # Each per-camera task builds its OWN S3 + Redis clients. In production each IEP
    # is its own process; here the tasks run concurrently under asyncio.gather, and
    # a boto3 client (driven via asyncio.to_thread) / a single redis connection are
    # not safe to share across concurrent callers. A passed-in client is used only
    # to ensure the bucket exists -- never shared into the workers.
    def _new_s3():
        return S3Client(settings)

    def _new_redis():
        import redis.asyncio as redis

        return redis.from_url(settings.REDIS_URL)

    await (s3_client or _new_s3()).ensure_bucket()

    # --- Phase 1: IEP1 ingestion (all cameras) -> S3 frames + manifest streams ---
    async def ingest(cam_id: str, video: str) -> None:
        rt = Iep1Runtime(plan.store_id, cam_id, settings,
                         s3_client=_new_s3(), redis_client=_new_redis())
        await rt.run(VideoFileSource(video, settings.sample_rate_fps, start_ms), start_ms)

    await asyncio.gather(*[ingest(c, v) for c, v in plan.cameras.items()])

    # --- Phase 2: IEP2 consumes manifests -> IEP3 reconciles ---
    repo = Iep3Repository(settings)
    reconciler = Reconciler(plan.store_id, repo, settings, plan.frame_px)
    coordinator = BatchCoordinator(expected_cameras=set(plan.cameras), on_ready=reconciler.process_batch)
    emitter = _InProcessEmitter(coordinator)

    async def consume(cam_id: str) -> None:
        cam_redis = _new_redis()
        rt = Iep2Runtime(plan.store_id, cam_id, settings)
        setup_kwargs = dict(events=emitter, warm_restart=False)
        setup_kwargs.update(overrides.get(cam_id, {}))
        await rt.setup(calibrations[cam_id], **setup_kwargs)
        source = RedisStreamFrameSource(cam_id, s3_client=_new_s3(), redis_client=cam_redis, settings=settings)
        # Bounded drain: stop once this camera's manifests are exhausted (finite
        # video). _DrainingSource wraps the stream source with a stop sentinel.
        await rt.run_from_iep1(_DrainingSource(source, cam_id, cam_redis, settings))

    await asyncio.gather(*[consume(c) for c in plan.cameras])
    await coordinator.drain()


class _DrainingSource:
    """Wraps RedisStreamFrameSource for the orchestrated (finite-video) demo:
    yields all currently-pending manifests for the camera, then stops -- so the
    IEP2 consumer returns instead of blocking forever on ``xreadgroup``. Production
    IEP2 uses the unbounded ``RedisStreamFrameSource`` directly (cameras never end)."""

    def __init__(self, source, camera_id, redis_client, settings):
        self._source = source
        self._stream = f"stream:iep1:{camera_id}"
        self._redis = redis_client
        self._s = settings

    async def windows(self):
        import json

        client = self._redis
        if client is None:
            import redis.asyncio as redis

            client = redis.from_url(self._s.REDIS_URL)
        entries = await client.xrange(self._stream)
        for msg_id, fields in entries:
            manifest = json.loads(fields[b"manifest"])
            yield self._source._to_batch(manifest), msg_id

    async def fetch_frames(self, batch):
        async for item in self._source.fetch_frames(batch):
            yield item

    async def ack(self, msg_id) -> None:
        # Demo drain reads via xrange (not a consumer group), so there is nothing
        # to ack. Production IEP2 uses RedisStreamFrameSource's group + ack directly.
        return None


async def load_calibrations(cam_ids: list[str]) -> dict:
    """Load demo CameraCalibration rows for the given cameras."""
    from sqlalchemy import select

    from common.db.engine import session_scope
    from common.models.shared_tables import CameraCalibration

    out = {}
    async with session_scope() as session:
        for cam_id in cam_ids:
            out[cam_id] = (
                await session.execute(select(CameraCalibration).where(CameraCalibration.cam_id == cam_id))
            ).scalar_one()
    return out


def _main() -> None:  # pragma: no cover - CLI wiring
    import argparse

    from common.db.engine import dispose_engine

    p = argparse.ArgumentParser(description="Run the IEP1->IEP2->IEP3 chain against demo videos")
    p.add_argument("--store-id", required=True)
    p.add_argument("--camera", action="append", required=True, help="camera_id=video_path (repeatable)")
    p.add_argument("--frame-px", type=int, default=1920 * 1080)
    p.add_argument("--direct", action="store_true",
                   help="fallback: IEP2 reads videos directly (no IEP1/S3/Redis frame transport)")
    args = p.parse_args()
    cameras = dict(c.split("=", 1) for c in args.camera)
    frame_px = {c: args.frame_px for c in cameras}

    async def _run():
        calibrations = await load_calibrations(list(cameras))
        plan = RunPlan(args.store_id, cameras, frame_px)
        if args.direct:
            await run(plan, calibrations)
        else:
            await run_via_iep1(plan, calibrations)
        await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    _main()
