"""Reconciler end-to-end (IEP3 spec §13): a 3-camera batch where Cam1 sees a
person in zone A and Cam2+Cam3 see the SAME person in zone B from two angles.
Asserts the zone-B person gets ONE Global ID across Cam2/Cam3, the zone-A person
a separate one, and exactly one canonical position per Global ID."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository
from tests.iep3.integration.seed import insert_centroid, insert_positions, new_uuid, onehot

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("44444444-4444-4444-4444-444444444444")


async def test_three_camera_scenario_one_global_across_cam2_cam3(pg):
    la, lb, lc = new_uuid(), new_uuid(), new_uuid()  # cam1 personX, cam2/cam3 personY
    await insert_centroid(la, "cam1", onehot(1))
    await insert_centroid(lb, "cam2", onehot(7))
    await insert_centroid(lc, "cam3", onehot(7))  # same appearance as lb

    await insert_positions(la, "cam1", [
        dict(timestamp_ms=500, floor_x=1.0, floor_y=1.0, zone_id="A", bbox_confidence=0.9, bbox_area=5000.0),
        dict(timestamp_ms=600, floor_x=1.1, floor_y=1.0, zone_id="A", bbox_confidence=0.9, bbox_area=5000.0),
    ])
    await insert_positions(lb, "cam2", [
        dict(timestamp_ms=1000, floor_x=10.0, floor_y=10.0, zone_id="B", bbox_confidence=0.9, bbox_area=4000.0),
        dict(timestamp_ms=1500, floor_x=10.0, floor_y=10.0, zone_id="B", bbox_confidence=0.9, bbox_area=4000.0),
    ])
    await insert_positions(lc, "cam3", [
        dict(timestamp_ms=2000, floor_x=10.2, floor_y=10.0, zone_id="B", bbox_confidence=0.9, bbox_area=8000.0),
        dict(timestamp_ms=2500, floor_x=10.2, floor_y=10.0, zone_id="B", bbox_confidence=0.9, bbox_area=8000.0),
    ])

    settings = get_settings()
    reconciler = Reconciler(STORE, Iep3Repository(settings), settings,
                            frame_px={"cam1": 10000, "cam2": 10000, "cam3": 10000})
    result = await reconciler.process_batch(0, (0, 60000))

    assert result["observations"] == 3
    assert result["new_locals"] == 3
    assert result["positions_written"] == 2  # one per global

    async def _gid(local_id):
        async with session_scope() as s:
            return (await s.execute(text(
                "SELECT global_id FROM global_local_mapping WHERE local_id=:l AND is_active=TRUE"),
                {"l": local_id})).scalar_one()

    g_a, g_b, g_c = await _gid(la), await _gid(lb), await _gid(lc)
    assert g_b == g_c  # Cam2 + Cam3 -> one Global ID
    assert g_a != g_b  # zone-A person distinct

    async with session_scope() as s:
        n_globals = (await s.execute(text("SELECT COUNT(*) FROM global_identities"))).scalar_one()
        n_canon = (await s.execute(text("SELECT COUNT(*) FROM global_tracking_history"))).scalar_one()
        # the zone-B canonical position comes from cam3 (larger box -> higher score)
        src = (await s.execute(text(
            "SELECT source_camera FROM global_tracking_history WHERE global_id=:g"), {"g": g_b})).scalar_one()
    assert n_globals == 2
    assert n_canon == 2
    assert src == "cam3"
