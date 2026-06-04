"""
IEP3 Reconciliation Service — entrypoint.
Long-running daemon. No HTTP server. No exposed port.

Startup sequence:
  1. Load and validate settings
  2. Create asyncpg pool, verify DB connectivity and required tables
  3. Create Redis client, verify connectivity
  4. Run startup orphan sweep
  5. Construct Reconciler (constructed once, reused per batch)
  6. Start BatchCoordinator loop (blocks until SIGTERM/SIGINT)
  7. Graceful shutdown: cancel coordinator, close Redis, close pool
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import redis.asyncio as aioredis

from app.coordinator import BatchCoordinator
from app.db import close_pool, create_pool, get_pool
from app.reconciler import Reconciler
from app.repository import Iep3Repository
from app.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("iep3")

REQUIRED_TABLES = {
    "tracking_history",
    "local_centroids",
    "global_identities",
    "global_local_mapping",
    "global_embeddings",
    "global_tracking_history",
}


async def _verify_db(pool) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY($1)
            """,
            list(REQUIRED_TABLES),
        )
        found = {r["table_name"] for r in rows}
        missing = REQUIRED_TABLES - found
        if missing:
            raise RuntimeError(
                f"Required tables missing: {missing}. "
                "Run A1 schema additions before starting IEP3."
            )
    logger.info("DB verified — all required tables present.")


async def _verify_redis(redis_client) -> None:
    await redis_client.ping()
    logger.info("Redis verified.")


async def _main() -> None:
    settings = get_settings()
    logger.info(
        "IEP3 starting  store_id=%s  expected_cameras=%s  "
        "window_seconds=%.1f  db_host=%s  redis=%s",
        settings.store_id,
        sorted(settings.expected_cameras),
        settings.window_seconds,
        settings.database_url_server.split("@")[-1].split("/")[0],
        settings.redis_url,
    )

    # ── Infrastructure ────────────────────────────────────────────────────────
    pool = await create_pool(settings.database_url_server)
    await _verify_db(pool)

    redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=False,
    )
    await _verify_redis(redis_client)

    # ── Repository ────────────────────────────────────────────────────────────
    repo = Iep3Repository(get_pool(), embedding_dim=settings.embedding_dim)

    # ── Startup orphan sweep ──────────────────────────────────────────────────
    swept = await repo.orphan_sweep()
    if swept > 0:
        logger.warning(
            "Orphan sweep removed %d incomplete GlobalIDs from prior crash.",
            swept,
        )

    # ── Reconciler ────────────────────────────────────────────────────────────
    reconciler = Reconciler(
        store_id=settings.store_id,
        repo=repo,
        settings=settings,
    )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received — stopping coordinator.")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # ── Coordinator ───────────────────────────────────────────────────────────
    coordinator = BatchCoordinator(
        redis_client=redis_client,
        store_id=settings.store_id,
        expected_cameras=settings.expected_cameras,
        on_ready=reconciler.process_batch,
        coordinator_timeout_s=settings.coordinator_timeout_s,
    )

    logger.info("IEP3 ready — listening on stream:iep2:batch_complete")
    coordinator_task = asyncio.create_task(
        coordinator.run(), name="iep3-coordinator"
    )

    # Block until shutdown signal
    await stop_event.wait()

    # ── Shutdown ──────────────────────────────────────────────────────────────
    coordinator_task.cancel()
    try:
        await coordinator_task
    except asyncio.CancelledError:
        pass

    await redis_client.aclose()
    await close_pool()
    logger.info("IEP3 shutdown complete.")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
