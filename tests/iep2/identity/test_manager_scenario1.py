"""Scenario 1 (IEP2 spec §9): a person occluded then re-identified keeps the
original Local ID, and the buffered temp positions are flushed under it."""

from __future__ import annotations

import pytest

from common.config import get_settings
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from tests.iep2.identity.helpers import (
    FakePersistence,
    LabelEmbedder,
    as_tracked,
    make_frame,
    person_det,
    tracker,
)

pytestmark = pytest.mark.asyncio

FRAME = make_frame(label=100)  # any crop -> mean 100 -> stable embedding


async def test_scenario1_reidentification_keeps_local_id_and_flushes_positions():
    s = get_settings()
    db = FakePersistence()
    mgr = LocalIdentityManager("cam1", LabelEmbedder(), db, s)

    # 1. Person A appears, LostPool empty -> fast path, fresh Local ID, position written
    detA = person_det(track_id=1, x=200, y=300)
    await mgr.process_frame(FRAME, [detA], tracker(new=as_tracked([detA])), timestamp_ms=1000)
    assert 1 in mgr.pools.active
    original = mgr.pools.active[1].local_id
    assert len(db.positions) == 1
    assert sum(1 for e in db.embeddings if e["is_init"]) == 1

    # 2. A walks behind a shelf -> tracker drops the track -> LostPool
    await mgr.process_frame(FRAME, [], tracker(lost=[1]), timestamp_ms=2000)
    assert 1 not in mgr.pools.active
    assert original in mgr.pools.lost

    # 3-4. A reappears with a NEW track id -> pending -> collects init embeddings -> ReID
    n = s.init_embeddings_count
    for i in range(n):
        det = person_det(track_id=2, x=200, y=300)
        kind = "new" if i == 0 else "confirmed"
        await mgr.process_frame(
            FRAME, [det], tracker(**{kind: as_tracked([det])}), timestamp_ms=3000 + i * 100
        )

    # re-identified: same Local ID, lost entry consumed, temp positions flushed
    assert 2 in mgr.pools.active
    assert mgr.pools.active[2].local_id == original
    assert original not in mgr.pools.lost
    flushed = [f for f in db.flushed if f["local_id"] == original]
    assert len(flushed) == 1 and flushed[0]["count"] == n


async def test_scenario1_failed_match_gets_fresh_local_id():
    s = get_settings()
    db = FakePersistence()
    mgr = LocalIdentityManager("cam1", LabelEmbedder(), db, s)

    detA = person_det(track_id=1, x=200, y=300)
    await mgr.process_frame(make_frame(50), [detA], tracker(new=as_tracked([detA])), timestamp_ms=1000)
    original = mgr.pools.active[1].local_id
    await mgr.process_frame(make_frame(50), [], tracker(lost=[1]), timestamp_ms=2000)

    # reappears with a DIFFERENT appearance (mean 200) -> below threshold -> new id
    n = s.init_embeddings_count
    for i in range(n):
        det = person_det(track_id=2, x=200, y=300)
        kind = "new" if i == 0 else "confirmed"
        await mgr.process_frame(make_frame(200), [det], tracker(**{kind: as_tracked([det])}),
                                timestamp_ms=3000 + i * 100)

    assert 2 in mgr.pools.active
    assert mgr.pools.active[2].local_id != original
