"""Warm-restart LostPool reconstruction from a real test database."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from common.config import get_settings
from common.db.engine import session_scope
from common.models.iep2_tables import LocalCentroid, LocalEmbedding, TrackingHistory
from common.utils.embeddings import serialize_embedding
from common.utils.time import now_ms
from services.iep2_vision.app.recovery import reconstruct_lost_pool

pytestmark = pytest.mark.asyncio


async def test_reconstructs_lost_entry_with_position_centroid_gallery(pg):
    settings = get_settings()
    dim = settings.embedding_dim
    lid = uuid.uuid4()
    recent = now_ms() - 1000  # within cutoff window

    centroid = np.linspace(0, 1, dim).astype(np.float32)
    async with session_scope() as s:
        s.add(TrackingHistory(local_id=lid, camera_id="cam1", timestamp_ms=recent - 100,
                              floor_x=1.0, floor_y=2.0, zone_id="A", bbox_confidence=0.9, bbox_area=5000))
        s.add(TrackingHistory(local_id=lid, camera_id="cam1", timestamp_ms=recent,
                              floor_x=3.0, floor_y=4.0, zone_id="A", bbox_confidence=0.9, bbox_area=5000))
        s.add(LocalCentroid(local_id=lid, camera_id="cam1",
                            centroid=serialize_embedding(centroid), updated_at_batch=2))
        s.add(LocalEmbedding(local_id=lid, captured_ts=recent, camera_id="cam1",
                             embedding=serialize_embedding(centroid), yolo_confidence=0.9, is_init=True))

    lost = await reconstruct_lost_pool("cam1", current_batch=7, settings=settings)

    assert lid in lost
    entry = lost[lid]
    assert (entry.last_floor_x, entry.last_floor_y) == (3.0, 4.0)  # latest position
    assert entry.last_seen_ts == recent
    assert entry.expiry_batch == 7 + settings.lost_pool_ttl_batches
    np.testing.assert_allclose(entry.centroid, centroid, atol=1e-6)
    assert len(entry.gallery) == 1


async def test_stale_positions_excluded(pg):
    settings = get_settings()
    lid = uuid.uuid4()
    stale = now_ms() - settings.lost_pool_ttl_batches * settings.batch_window_seconds * 1000 - 10_000
    async with session_scope() as s:
        s.add(TrackingHistory(local_id=lid, camera_id="cam1", timestamp_ms=stale,
                              floor_x=1.0, floor_y=2.0, zone_id="A", bbox_confidence=0.9, bbox_area=5000))
        s.add(LocalCentroid(local_id=lid, camera_id="cam1",
                            centroid=serialize_embedding(np.zeros(settings.embedding_dim, np.float32)),
                            updated_at_batch=1))

    lost = await reconstruct_lost_pool("cam1", current_batch=0, settings=settings)
    assert lid not in lost  # older than the cutoff
