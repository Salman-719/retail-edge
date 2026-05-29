"""ReID resolution for a pending track (IEP2 spec §8).

Fires once a pending track has collected ``init_embeddings_count`` embeddings.
SpatialCheck (gate against the LostPool) -> ReIDMatch (mean embedding vs each
survivor centroid) -> Validate (threshold). Returns a decision the manager
applies; it does not mutate the pools.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np

from common.utils.embeddings import cosine_similarity, l2_normalize
from services.iep2_vision.app.identity.gates import spatial_temporal_gate


@dataclass
class Resolution:
    local_id: uuid.UUID
    matched: bool  # True = re-identified an existing LocalID from the LostPool
    matched_lost_local_id: uuid.UUID | None


def resolve(pending, pools, settings) -> Resolution:
    # 1. SpatialCheck against the LostPool
    survivors = [
        e
        for e in pools.lost.values()
        if spatial_temporal_gate(
            pending.last_floor_x,
            pending.last_floor_y,
            pending.last_seen_ts,
            e.last_floor_x,
            e.last_floor_y,
            e.last_seen_ts,
            settings.max_walking_speed_mps,
        )
    ]

    # 2. No survivors -> brand new identity
    if not survivors:
        return Resolution(local_id=uuid.uuid4(), matched=False, matched_lost_local_id=None)

    # 3. ReIDMatch: mean of pending embeddings vs each survivor centroid
    query = l2_normalize(np.mean(pending.embeddings, axis=0))
    best, best_score = None, -1.0
    for e in survivors:
        score = cosine_similarity(query, e.centroid)
        if score > best_score:
            best, best_score = e, score

    # 4. Validate against threshold
    if best is not None and best_score >= settings.reid_match_threshold:
        return Resolution(local_id=best.local_id, matched=True, matched_lost_local_id=best.local_id)
    return Resolution(local_id=uuid.uuid4(), matched=False, matched_lost_local_id=None)
