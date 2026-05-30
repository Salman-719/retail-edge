"""on_empty_window: an offline/empty window moves active tracks to the Lost pool
and clears pending, so returnees can be re-identified and IEP3 still gets a batch."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from common.config import get_settings
from services.iep2_vision.app.identity.manager import LocalIdentityManager
from services.iep2_vision.app.identity.pools import ActiveTrack, PendingTrack
from services.iep2_vision.app.identity.gallery import EmbeddingGallery
from tests.iep2.identity.helpers import FakePersistence, LabelEmbedder

pytestmark = pytest.mark.asyncio


def _active(track_id: int) -> ActiveTrack:
    g = EmbeddingGallery(get_settings().gallery_max_size, get_settings().centroid_ema_alpha)
    g.add(np.ones(512, dtype=np.float32))
    return ActiveTrack(track_id=track_id, local_id=uuid.uuid4(), camera_id="cam1",
                       floor_x=1.0, floor_y=2.0, zone_id="A", last_seen_ts=1000,
                       bbox_confidence=0.9, confirmed_frames=10, sample_counter=0, gallery=g)


async def test_empty_window_moves_active_to_lost_and_clears_pending():
    mgr = LocalIdentityManager("cam1", LabelEmbedder(), FakePersistence(), get_settings())
    mgr.pools.active[1] = _active(1)
    mgr.pools.active[2] = _active(2)
    mgr.pools.pending[3] = PendingTrack(track_id=3, camera_id="cam1", created_ts=500)

    result = mgr.on_empty_window()

    assert result["moved_to_lost"] == 2
    assert mgr.pools.active == {}
    assert mgr.pools.pending == {}
    assert len(mgr.pools.lost) == 2  # both former actives are now ReID candidates


async def test_empty_window_noop_when_nothing_active():
    mgr = LocalIdentityManager("cam1", LabelEmbedder(), FakePersistence(), get_settings())
    assert mgr.on_empty_window()["moved_to_lost"] == 0
