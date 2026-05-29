"""seed_calibration writes/updates demo camera_calibrations rows."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.db.engine import session_scope
from tools.seed_calibration import seed_calibration

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("55555555-5555-5555-5555-555555555555")


async def test_seed_inserts_rows(pg):
    await seed_calibration(STORE, ["cam1", "cam2", "cam3"])
    async with session_scope() as s:
        rows = (await s.execute(text("SELECT cam_id FROM camera_calibrations ORDER BY cam_id"))).scalars().all()
    assert rows == ["cam1", "cam2", "cam3"]


async def test_seed_is_idempotent(pg):
    await seed_calibration(STORE, ["cam1"])
    await seed_calibration(STORE, ["cam1"])  # upsert, not a duplicate
    async with session_scope() as s:
        n = (await s.execute(text("SELECT COUNT(*) FROM camera_calibrations WHERE cam_id='cam1'"))).scalar_one()
    assert n == 1
