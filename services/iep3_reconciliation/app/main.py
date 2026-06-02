"""IEP3 reconciliation service entrypoint.

Single-instance, batch-triggered: the coordinator consumes IEP2 batch_complete
events and triggers the reconciler when all cameras report. ``cameras`` and
``frame_px`` (per-camera frame pixel area for selection normalisation) come from
store config; M6 supplies them when wiring the full stack.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from common.config import get_settings
from common.db.engine import dispose_engine, session_scope
from common.logging_conf import configure_logging
from services.iep3_reconciliation.app.coordinator import BatchCoordinator
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository

log = logging.getLogger("iep3-reconciliation")

# How often to re-read the store's camera list from the DB so GUI changes
# (cameras added/removed) take effect without restarting the pod.
CAMERA_REFRESH_SECONDS = 30


async def fetch_store_cameras(store_id) -> set[str]:
    """Camera IDs (physical_cameras.id) for the store's ACTIVE config version.
    Matches the camera_id IEP2 emits in batch_complete events."""
    async with session_scope() as session:
        rows = await session.execute(
            text(
                """
                SELECT pc.id::text AS camera_id
                FROM camera_configs cc
                JOIN physical_cameras pc ON pc.id = cc.physical_camera_id
                JOIN store_config_versions v ON v.id = cc.version_id
                WHERE pc.store_id = :store_id AND v.status = 'active'
                """
            ),
            {"store_id": str(store_id)},
        )
        return {r[0] for r in rows.fetchall()}


async def _refresh_cameras_loop(store_id, coordinator: BatchCoordinator) -> None:
    """Periodically sync the coordinator's expected-camera set with the DB."""
    while True:
        await asyncio.sleep(CAMERA_REFRESH_SECONDS)
        try:
            cams = await fetch_store_cameras(store_id)
            if cams and cams != coordinator._expected:
                log.info("Camera set changed for store %s: %s", store_id, sorted(cams))
                coordinator._expected = cams
        except Exception:
            log.exception("camera refresh failed (keeping current set)")


async def run_service(store_id, cameras: list[str] | None, frame_px: dict[str, int],
                      timeout_seconds: float | None = None) -> None:
    settings = get_settings()
    configure_logging("iep3-reconciliation")

    import os

    metrics_port = os.getenv("METRICS_PORT")
    if metrics_port:
        from services.iep3_reconciliation.app.metrics import start_metrics_server

        start_metrics_server(int(metrics_port))

    # Cameras from explicit arg (testing) or the DB (production, GUI-driven).
    expected = set(cameras) if cameras else await fetch_store_cameras(store_id)
    log.info("IEP3 starting for store %s with cameras: %s", store_id, sorted(expected))

    repo = Iep3Repository(settings)
    reconciler = Reconciler(store_id, repo, settings, frame_px)
    coordinator = BatchCoordinator(
        expected_cameras=expected,
        on_ready=reconciler.process_batch,
        timeout_seconds=timeout_seconds or settings.batch_window_seconds * 2,
    )
    refresher = asyncio.create_task(_refresh_cameras_loop(store_id, coordinator))
    try:
        await coordinator.run()
    finally:
        refresher.cancel()
        await dispose_engine()


def _parse_frame_px(raw: str) -> dict[str, int]:
    return {kv.split("=")[0]: int(kv.split("=")[1]) for kv in raw.split(",") if "=" in kv}


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import os

    p = argparse.ArgumentParser(description="IEP3 cross-camera reconciliation coordinator")
    # Args optional — fall back to env so the k8s pod can run without CLI flags.
    p.add_argument("--store-id", default=os.getenv("STORE_ID"))
    p.add_argument("--cameras", default=os.getenv("IEP3_CAMERA_IDS", ""),
                   help="comma-separated camera ids (or set IEP3_CAMERA_IDS env)")
    p.add_argument("--frame-px", default=os.getenv("IEP3_FRAME_PX", ""),
                   help="cam=pixels,cam=pixels (or set IEP3_FRAME_PX env)")
    a = p.parse_args()

    if not a.store_id:
        raise SystemExit("STORE_ID is required (env or --store-id)")

    # Cameras are read from the DB (store's active config) unless explicitly
    # passed for testing. The coordinator tolerates an empty set at startup and
    # the background refresh loop picks up cameras as soon as they're configured
    # in the GUI — no restart, no IEP3_CAMERA_IDS needed.
    cameras = [c for c in a.cameras.split(",") if c] or None
    asyncio.run(run_service(a.store_id, cameras, _parse_frame_px(a.frame_px)))
