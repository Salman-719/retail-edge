"""Lightweight orchestrator -- a stand-in for EEP, sufficient to run and demo the
IEP2+IEP3 subsystem.

Launches one IEP2 runtime per camera (each an asyncio task) against its video with
a shared ``start_ms`` so timelines align, and runs IEP3 reconciliation in the same
process. Instead of round-tripping batch_complete through Redis, IEP2 runtimes emit
to an in-process adapter that calls the coordinator directly -- the coordinator
still enforces the "wait for all cameras" rule, and the Redis path remains the
deployment option. For production this is replaced by EEP; the orchestrator stays
minimal -- its only job is to exercise the full chain for tests and the demo.
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

    p = argparse.ArgumentParser(description="Run IEP2+IEP3 against demo videos")
    p.add_argument("--store-id", required=True)
    p.add_argument("--camera", action="append", required=True, help="camera_id=video_path (repeatable)")
    p.add_argument("--frame-px", type=int, default=1920 * 1080)
    args = p.parse_args()
    cameras = dict(c.split("=", 1) for c in args.camera)
    frame_px = {c: args.frame_px for c in cameras}

    async def _run():
        calibrations = await load_calibrations(list(cameras))
        await run(RunPlan(args.store_id, cameras, frame_px), calibrations)
        await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    _main()
