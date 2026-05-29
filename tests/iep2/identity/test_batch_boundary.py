"""LostPool TTL is enforced only at batch boundaries, and entries expire exactly
at expiry_batch (IEP2 spec §11; M3 review issues B4/19)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from common.config import get_settings
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from services.iep2_vision.app.identity.pools import LostEntry
from tests.iep2.identity.helpers import FakePersistence, LabelEmbedder, make_frame, tracker

pytestmark = pytest.mark.asyncio


def _mgr() -> LocalIdentityManager:
    return LocalIdentityManager("cam1", LabelEmbedder(), FakePersistence(), get_settings())


def _seed_lost(mgr: LocalIdentityManager, expiry_batch: int) -> uuid.UUID:
    lid = uuid.uuid4()
    mgr.pools.lost[lid] = LostEntry(
        local_id=lid, camera_id="cam1", last_floor_x=0, last_floor_y=0, last_seen_ts=0,
        expiry_batch=expiry_batch, centroid=np.zeros(512, dtype=np.float32), gallery=[],
    )
    return lid


async def test_expires_exactly_at_expiry_batch_not_before():
    mgr = _mgr()
    lid = _seed_lost(mgr, expiry_batch=3)

    assert mgr.on_batch_boundary(2)["pruned_lost"] == 0
    assert lid in mgr.pools.lost  # not yet
    assert mgr.on_batch_boundary(3)["pruned_lost"] == 1
    assert lid not in mgr.pools.lost  # expired exactly at batch 3


async def test_no_pruning_per_frame():
    mgr = _mgr()
    lid = _seed_lost(mgr, expiry_batch=0)  # already past expiry
    # processing frames must NOT prune -- only the boundary call does
    await mgr.process_frame(make_frame(10), [], tracker(), timestamp_ms=500)
    await mgr.process_frame(make_frame(10), [], tracker(), timestamp_ms=1000)
    assert lid in mgr.pools.lost
    assert mgr.on_batch_boundary(0)["pruned_lost"] == 1
    assert lid not in mgr.pools.lost
