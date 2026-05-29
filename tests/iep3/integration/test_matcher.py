"""Process 1 (ReID matcher) against a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep3_reconciliation.app.reader import LocalObservation
from services.iep3_reconciliation.app.reid.matcher import ReidMatcher
from services.iep3_reconciliation.app.repository import Iep3Repository
from tests.iep3.integration.seed import insert_centroid, new_uuid, onehot

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _obs(local_id, camera_id, x, y, first_ts, last_ts):
    return LocalObservation(local_id=local_id, camera_id=camera_id, last_floor_x=x, last_floor_y=y,
                            last_seen_ts=last_ts, first_seen_ts=first_ts, best_confidence=0.9,
                            best_bbox_area=5000.0)


async def _matcher():
    return ReidMatcher(Iep3Repository(get_settings()), get_settings())


async def _global_count() -> int:
    async with session_scope() as s:
        return (await s.execute(text("SELECT COUNT(*) FROM global_identities"))).scalar_one()


async def _global_for_local(local_id):
    async with session_scope() as s:
        return (await s.execute(text(
            "SELECT global_id FROM global_local_mapping WHERE local_id=:l AND is_active=TRUE"),
            {"l": local_id})).scalar_one_or_none()


async def test_new_local_with_no_candidates_creates_global(pg):
    la = new_uuid()
    await insert_centroid(la, "cam1", onehot(1))
    matcher = await _matcher()
    async with session_scope() as s:
        await matcher.link_new_locals(s, STORE, [_obs(la, "cam1", 0, 0, 500, 600)], batch=0)
    assert await _global_count() == 1
    assert await _global_for_local(la) is not None


async def test_cross_camera_same_person_links_to_one_global(pg):
    la, lb = new_uuid(), new_uuid()
    await insert_centroid(la, "cam1", onehot(3))
    await insert_centroid(lb, "cam2", onehot(3))  # same appearance
    matcher = await _matcher()
    async with session_scope() as s:
        # input unordered; matcher must process earliest first_seen first
        await matcher.link_new_locals(
            s, STORE,
            [_obs(lb, "cam2", 0.2, 0.0, 1000, 1500), _obs(la, "cam1", 0.0, 0.0, 500, 600)],
            batch=0,
        )
    assert await _global_count() == 1
    assert await _global_for_local(la) == await _global_for_local(lb)


async def test_same_camera_candidate_skipped(pg):
    la, lc = new_uuid(), new_uuid()
    await insert_centroid(la, "cam1", onehot(3))
    await insert_centroid(lc, "cam1", onehot(3))  # identical, but SAME camera
    matcher = await _matcher()
    async with session_scope() as s:
        await matcher.link_new_locals(
            s, STORE,
            [_obs(la, "cam1", 0.0, 0.0, 500, 600), _obs(lc, "cam1", 0.1, 0.0, 1000, 1100)],
            batch=0,
        )
    assert await _global_count() == 2  # not cross-matched within the same camera
    assert await _global_for_local(la) != await _global_for_local(lc)


async def test_match_reactivates_lost_global(pg):
    lb, ld = new_uuid(), new_uuid()
    await insert_centroid(lb, "cam2", onehot(5))
    await insert_centroid(ld, "cam3", onehot(5))
    matcher = await _matcher()
    async with session_scope() as s:
        await matcher.link_new_locals(s, STORE, [_obs(lb, "cam2", 0, 0, 500, 600)], batch=0)
    gid = await _global_for_local(lb)
    async with session_scope() as s:
        await s.execute(text("UPDATE global_identities SET state='lost', lost_since_batch=0 "
                             "WHERE global_id=:g"), {"g": gid})
    async with session_scope() as s:
        await matcher.link_new_locals(s, STORE, [_obs(ld, "cam3", 0.2, 0.0, 1000, 1500)], batch=1)

    async with session_scope() as s:
        state = (await s.execute(text("SELECT state FROM global_identities WHERE global_id=:g"),
                                 {"g": gid})).scalar_one()
    assert state == "active"  # reactivated on cross-camera re-match
    assert await _global_for_local(ld) == gid
