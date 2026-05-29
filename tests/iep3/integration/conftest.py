"""Integration fixtures for M5 (real PostgreSQL). See tests/integration_support.py."""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.integration_support import RUN, prepare_db, reset_settings_and_engine


@pytest_asyncio.fixture(scope="function")
async def pg():
    if not RUN:
        pytest.skip("integration test (set RV_RUN_INTEGRATION=1 + DATABASE_URL)")
    reset_settings_and_engine()
    await prepare_db()
    yield
    from common.db.engine import dispose_engine

    await dispose_engine()
