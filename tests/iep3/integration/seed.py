"""Seeding helpers for IEP3 integration tests (write IEP2 + IEP3 rows)."""

from __future__ import annotations

import uuid

import numpy as np

from common.db.engine import session_scope
from common.models.iep2_tables import LocalCentroid, TrackingHistory
from common.models.iep3_tables import GlobalIdentity, GlobalLocalMapping
from common.utils.embeddings import serialize_embedding


def onehot(i: int, dim: int = 512) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


async def insert_centroid(local_id, camera_id, vec, batch: int = 0) -> None:
    async with session_scope() as s:
        s.add(LocalCentroid(local_id=local_id, camera_id=camera_id,
                            centroid=serialize_embedding(vec), updated_at_batch=batch))


async def insert_positions(local_id, camera_id, rows: list[dict]) -> None:
    """rows: dicts with timestamp_ms, floor_x, floor_y, zone_id, bbox_confidence, bbox_area."""
    async with session_scope() as s:
        for r in rows:
            s.add(TrackingHistory(local_id=local_id, camera_id=camera_id, **r))


async def insert_global(global_id, store_id, *, state="active", last_floor=(0.0, 0.0),
                        last_seen_ts=0, first_seen_ts=0, lost_since_batch=None) -> None:
    async with session_scope() as s:
        s.add(GlobalIdentity(global_id=global_id, store_id=store_id, first_seen_ts=first_seen_ts,
                             last_seen_ts=last_seen_ts, state=state, lost_since_batch=lost_since_batch,
                             last_floor_x=last_floor[0], last_floor_y=last_floor[1]))


async def insert_mapping(global_id, camera_id, local_id, *, is_active=True,
                         linked_at_batch=0, last_seen_batch=0) -> None:
    async with session_scope() as s:
        s.add(GlobalLocalMapping(global_id=global_id, camera_id=camera_id, local_id=local_id,
                                 is_active=is_active, linked_at_batch=linked_at_batch,
                                 last_seen_batch=last_seen_batch))


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
