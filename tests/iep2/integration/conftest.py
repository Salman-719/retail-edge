"""Integration fixtures for M4 (real PostgreSQL).

Gated on RV_RUN_INTEGRATION=1 so the default unit run stays DB-free. Point
DATABASE_URL at a throwaway Postgres before running:

    DATABASE_URL=postgresql+asyncpg://rv:rv@localhost:5544/rvtest \
    RV_RUN_INTEGRATION=1 pytest tests/iep2/integration -v
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

RUN = os.getenv("RV_RUN_INTEGRATION") == "1"


def _reset_settings_and_engine():
    """Drop cached singletons so the current DATABASE_URL env is picked up."""
    import common.config as config_module
    import common.db.engine as engine_module

    config_module._settings = None
    engine_module._engine = None
    engine_module._session_factory = None


@pytest_asyncio.fixture(scope="function")
async def pg():
    if not RUN:
        pytest.skip("integration test (set RV_RUN_INTEGRATION=1 + DATABASE_URL)")
    _reset_settings_and_engine()

    from common.db.engine import dispose_engine, get_engine
    from common.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # clean slate between tests
        await conn.exec_driver_sql(
            "TRUNCATE tracking_history, local_embeddings, local_centroids, "
            "global_tracking_history, global_local_mapping, global_embeddings, "
            "global_identities, camera_calibrations RESTART IDENTITY CASCADE"
        )
    yield
    await dispose_engine()
