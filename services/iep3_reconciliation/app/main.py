"""IEP3 reconciliation service entrypoint.

Single-instance, batch-triggered: the coordinator consumes IEP2 batch_complete
events and triggers the reconciler when all cameras report. ``cameras`` and
``frame_px`` (per-camera frame pixel area for selection normalisation) come from
store config; M6 supplies them when wiring the full stack.
"""

from __future__ import annotations

import asyncio

from common.config import get_settings
from common.db.engine import dispose_engine
from common.logging_conf import configure_logging
from services.iep3_reconciliation.app.coordinator import BatchCoordinator
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository


async def run_service(store_id, cameras: list[str], frame_px: dict[str, int],
                      timeout_seconds: float | None = None) -> None:
    settings = get_settings()
    configure_logging("iep3-reconciliation")
    repo = Iep3Repository(settings)
    reconciler = Reconciler(store_id, repo, settings, frame_px)
    coordinator = BatchCoordinator(
        expected_cameras=set(cameras),
        on_ready=reconciler.process_batch,
        timeout_seconds=timeout_seconds or settings.batch_window_seconds * 2,
    )
    try:
        await coordinator.run()
    finally:
        await dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    import argparse

    p = argparse.ArgumentParser(description="IEP3 cross-camera reconciliation coordinator")
    p.add_argument("--store-id", required=True)
    p.add_argument("--cameras", required=True, help="comma-separated camera ids")
    p.add_argument("--frame-px", default="", help="cam=pixels,cam=pixels (selection normalisation)")
    a = p.parse_args()
    frame_px = {kv.split("=")[0]: int(kv.split("=")[1]) for kv in a.frame_px.split(",") if "=" in kv}
    asyncio.run(run_service(a.store_id, a.cameras.split(","), frame_px))
