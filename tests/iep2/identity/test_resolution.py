"""ReID resolution decisions (SpatialCheck -> ReIDMatch -> Validate)."""

from __future__ import annotations

import uuid

import numpy as np

from common.config import get_settings
from services.iep2_vision.app.identity.pools import IdentityPools, LostEntry, PendingTrack
from services.iep2_vision.app.identity.resolution import resolve


def _onehot(i: int, dim: int = 512) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


def _pending(emb: np.ndarray, x=1.0, y=0.0, ts=1000) -> PendingTrack:
    p = PendingTrack(track_id=1, camera_id="cam1", created_ts=0)
    p.embeddings = [emb, emb]
    p.last_floor_x, p.last_floor_y, p.last_seen_ts = x, y, ts
    return p


def _lost(centroid: np.ndarray, x=0.0, y=0.0, ts=0) -> LostEntry:
    return LostEntry(local_id=uuid.uuid4(), camera_id="cam1", last_floor_x=x, last_floor_y=y,
                     last_seen_ts=ts, expiry_batch=10, centroid=centroid, gallery=[centroid])


def test_empty_lost_pool_creates_new_identity():
    pools = IdentityPools()
    res = resolve(_pending(_onehot(3)), pools, get_settings())
    assert res.matched is False and res.matched_lost_local_id is None


def test_high_similarity_survivor_matched():
    pools = IdentityPools()
    entry = _lost(_onehot(3))  # nearby + same embedding
    pools.lost[entry.local_id] = entry
    res = resolve(_pending(_onehot(3)), pools, get_settings())
    assert res.matched is True
    assert res.matched_lost_local_id == entry.local_id
    assert res.local_id == entry.local_id


def test_below_threshold_creates_new_identity():
    pools = IdentityPools()
    entry = _lost(_onehot(7))  # nearby but different appearance
    pools.lost[entry.local_id] = entry
    res = resolve(_pending(_onehot(3)), pools, get_settings())
    assert res.matched is False


def test_spatially_implausible_survivor_filtered_out():
    pools = IdentityPools()
    # same appearance but 100 m away within 1 s -> gate removes it -> new identity
    entry = _lost(_onehot(3), x=100.0, y=100.0, ts=0)
    pools.lost[entry.local_id] = entry
    res = resolve(_pending(_onehot(3), x=0.0, y=0.0, ts=1000), pools, get_settings())
    assert res.matched is False


def test_competing_survivors_pick_highest_similarity():
    pools = IdentityPools()
    good = _lost(_onehot(3))
    weak = _lost((_onehot(3) + _onehot(4)))  # lower cosine to the query
    for e in (good, weak):
        pools.lost[e.local_id] = e
    res = resolve(_pending(_onehot(3)), pools, get_settings())
    assert res.matched is True and res.matched_lost_local_id == good.local_id
