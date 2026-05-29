"""Shared helpers for integration tests against a real PostgreSQL.

Gated on RV_RUN_INTEGRATION=1. Point DATABASE_URL at a throwaway Postgres:

    DATABASE_URL=postgresql+asyncpg://rv:rv@localhost:5544/rvtest \
    RV_RUN_INTEGRATION=1 pytest tests/iep2/integration tests/iep3/integration -v
"""

from __future__ import annotations

import os

RUN = os.getenv("RV_RUN_INTEGRATION") == "1"

_TABLES = (
    "tracking_history, local_embeddings, local_centroids, "
    "global_tracking_history, global_local_mapping, global_embeddings, "
    "global_identities, camera_calibrations"
)


def reset_settings_and_engine() -> None:
    """Drop cached singletons so the current DATABASE_URL env is picked up."""
    import common.config as config_module
    import common.db.engine as engine_module

    config_module._settings = None
    engine_module._engine = None
    engine_module._session_factory = None


async def prepare_db() -> None:
    """Create the subsystem tables (idempotent) and truncate for a clean slate."""
    from common.db.engine import get_engine
    from common.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
