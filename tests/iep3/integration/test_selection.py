"""Process 2 (position selection) against a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep3_reconciliation.app.repository import Iep3Repository
from services.iep3_reconciliation.app.selection import PositionSelector
from tests.iep3.integration.seed import insert_global, insert_mapping, insert_positions, new_uuid

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("22222222-2222-2222-2222-222222222222")


async def test_best_source_one_row_per_global(pg):
    gid = new_uuid()
    lb, lc = new_uuid(), new_uuid()
    await insert_global(gid, STORE)
    await insert_mapping(gid, "cam2", lb)
    await insert_mapping(gid, "cam3", lc)
    # cam2: small box; cam3: large box (should win on area weight)
    await insert_positions(lb, "cam2", [dict(timestamp_ms=1000, floor_x=10.0, floor_y=10.0,
                                             zone_id="B", bbox_confidence=0.8, bbox_area=2000.0)])
    await insert_positions(lc, "cam3", [dict(timestamp_ms=1100, floor_x=10.2, floor_y=10.0,
                                             zone_id="B", bbox_confidence=0.8, bbox_area=9000.0)])

    selector = PositionSelector(Iep3Repository(get_settings()), get_settings(),
                                frame_pixels_by_camera={"cam2": 10000, "cam3": 10000})
    async with session_scope() as s:
        n = await selector.write_canonical_positions(s, STORE, batch=0, window_start=0, window_end=60000)
    assert n == 1

    async with session_scope() as s:
        rows = (await s.execute(text(
            "SELECT source_camera, source_local_id FROM global_tracking_history WHERE global_id=:g"),
            {"g": gid})).all()
    assert len(rows) == 1  # exactly one canonical row per global per batch
    assert rows[0].source_camera == "cam3"  # larger box wins
    assert rows[0].source_local_id == lc
