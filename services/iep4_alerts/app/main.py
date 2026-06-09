"""IEP4 Alert Evaluation Daemon — entrypoint.
Long-running asyncio daemon. One process per store. No HTTP port, no gRPC.

Startup:
  1. Load + validate settings
  2. Create asyncpg pool, verify connectivity + required tables
  3. Construct repository + daemon
  4. Run the evaluation loop until SIGTERM/SIGINT
  5. Graceful shutdown
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from app.daemon import AlertDaemon
from app.db import close_pool, create_pool, get_pool
from app.metrics import start_metrics_server
from app.persistence.postgres import AlertRepository
from app.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("iep4")

REQUIRED_TABLES = {
    "global_tracking_history",
    "global_identities",
    "active_person_state",
    "zone_transition_log",
    "visit_sessions",
    "alert_rules",
    "alert_rule_zones",
    "alert_state",
    "alerts",
}


async def _verify_db(pool) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY($1)
            """,
            list(REQUIRED_TABLES),
        )
        found = {r["table_name"] for r in rows}
        missing = REQUIRED_TABLES - found
        if missing:
            raise RuntimeError(
                f"Required tables missing: {missing}. "
                "Apply migrations 0010 (SPEC-001) and 0011 (SPEC-003) before starting IEP4."
            )
    logger.info("DB verified — all required tables present.")


async def _main() -> None:
    settings = get_settings()
    logger.info(
        "IEP4 starting  store_id=%s  evaluation_batches=%d  window_seconds=%.1f  "
        "environment=%s  email_enabled=%s  db_host=%s",
        settings.store_id, settings.evaluation_batches, settings.window_seconds,
        settings.environment, settings.email_enabled,
        settings.database_url_server.split("@")[-1].split("/")[0],
    )

    # Prometheus side HTTP server (same pattern as IEP1/IEP2). Scraped on :8004,
    # job "iep4". Started before the loop so the target is UP from readiness.
    metrics_port = int(os.environ.get("IEP4_METRICS_PORT", "8004"))
    start_metrics_server(metrics_port)
    logger.info("Prometheus metrics server started on :%d", metrics_port)

    pool = await create_pool(settings.database_url_server)
    await _verify_db(pool)

    repo = AlertRepository(get_pool(), store_id=settings.store_id)
    daemon = AlertDaemon(settings, repo)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received — stopping daemon.")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("IEP4 ready — evaluating store %s", settings.store_id)
    await daemon.run(stop_event)

    await close_pool()
    logger.info("IEP4 shutdown complete.")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
