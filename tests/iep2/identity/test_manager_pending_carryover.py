"""A pending track with < init_embeddings_count embeddings at batch end carries
over and resolves in the next batch (IEP2 spec §11.2 / §14)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from common.config import get_settings
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from services.iep2_vision.app.identity.pools import LostEntry
from tests.iep2.identity.helpers import (
    FakePersistence,
    LabelEmbedder,
    as_tracked,
    make_frame,
    person_det,
    tracker,
)

pytestmark = pytest.mark.asyncio


def _onehot(i: int, dim: int = 512) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


async def test_pending_carries_over_and_resolves_next_batch():
    s = get_settings()
    n = s.init_embeddings_count
    assert n >= 3  # test needs to split the embeddings across two batches

    db = FakePersistence()
    mgr = LocalIdentityManager("cam1", LabelEmbedder(), db, s)

    # Seed a lost identity (so a new track takes the pending/ReID path).
    lid = uuid.uuid4()
    mgr.pools.lost[lid] = LostEntry(
        local_id=lid, camera_id="cam1", last_floor_x=240, last_floor_y=300,
        last_seen_ts=0, expiry_batch=5, centroid=_onehot(100), gallery=[_onehot(100)],
    )
    frame = make_frame(100)

    # Batch 0: only 2 of n embeddings collected -> pending carries over.
    for i in range(2):
        det = person_det(track_id=7, x=200, y=300)
        kind = "new" if i == 0 else "confirmed"
        await mgr.process_frame(frame, [det], tracker(**{kind: as_tracked([det])}), timestamp_ms=100 + i * 100)
    metrics = mgr.on_batch_boundary(0)
    assert metrics["pending_carryover"] == 1
    assert 7 in mgr.pools.pending and len(mgr.pools.pending[7].embeddings) == 2
    assert lid in mgr.pools.lost  # not expired (expiry_batch=5 > 0)

    # Batch 1: remaining embeddings -> resolves to the seeded Local ID.
    for i in range(2, n):
        det = person_det(track_id=7, x=200, y=300)
        await mgr.process_frame(frame, [det], tracker(confirmed=as_tracked([det])), timestamp_ms=1000 + i * 100)

    assert 7 not in mgr.pools.pending
    assert 7 in mgr.pools.active
    assert mgr.pools.active[7].local_id == lid
    assert lid not in mgr.pools.lost
