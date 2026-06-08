"""IEP5 End-of-Shift Analytics Job — entrypoint.

Runs once to completion and exits: 0 on success (or already-completed /
empty-shift), non-zero on preflight failure or error. No HTTP port, no daemon,
no Redis. Kubernetes (prod) / Docker Compose run (dev) handles retries.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from app.db import close_pool, create_pool, get_pool
from app.persistence.postgres import AnalyticsRepository
from app.pipeline import AnalyticsPipeline
from app.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("iep5")

REQUIRED_TABLES = {
    "global_tracking_history", "visit_sessions", "zone_transition_log",
    "active_person_state", "alerts", "alert_rule_zones", "shift_instances",
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
        public_ok = REQUIRED_TABLES - {r["table_name"] for r in rows}
        analytics_n = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'analytics'"
        )
    if public_ok:
        raise RuntimeError(f"Required tables missing: {public_ok}")
    if not analytics_n:
        raise RuntimeError("analytics schema is empty — apply migration 0010 (SPEC-001)")


async def _main() -> int:
    settings = get_settings()
    logger.info(
        "IEP5 starting  store_id=%s  shift_date=%s  db_host=%s",
        settings.store_id, settings.shift_date,
        settings.database_url_server.split("@")[-1].split("/")[0],
    )

    pool = await create_pool(settings.database_url_server)
    try:
        await _verify_db(pool)
        repo = AnalyticsRepository(get_pool(), store_id=settings.store_id)
        pipeline = AnalyticsPipeline(settings, repo)
        return await pipeline.run()
    finally:
        await close_pool()


def main() -> None:
    try:
        code = asyncio.run(_main())
    except Exception:
        logger.exception("IEP5 failed")
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
