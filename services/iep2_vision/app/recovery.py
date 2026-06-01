"""Warm-restart LostPool reconstruction from PostgreSQL (IEP2 spec §13).

On startup the tracker always begins fresh, but the LostPool is reconstructed
from persisted state (latest position per Local ID from ``tracking_history``,
centroid from ``local_centroids``, gallery from ``local_embeddings``) so a person
who was occluded at crash time can still be re-identified after restart.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from common.db.engine import session_scope
from common.utils.embeddings import deserialize_embedding
from common.utils.time import now_ms
from services.iep2_vision.app.identity.pools import LostEntry


async def reconstruct_lost_pool(camera_id: str, current_batch: int, settings) -> dict[uuid.UUID, LostEntry]:
    """Returns ``{local_id: LostEntry}`` to seed the manager's LostPool."""
    cutoff = now_ms() - settings.lost_pool_ttl_batches * settings.batch_window_seconds * 1000
    lost: dict[uuid.UUID, LostEntry] = {}
    async with session_scope() as session:
        rows = await session.execute(
            text(
                """
                SELECT DISTINCT ON (local_id) local_id, floor_x, floor_y, timestamp_ms
                FROM tracking_history
                WHERE camera_id = :cam AND timestamp_ms > :cutoff
                ORDER BY local_id, timestamp_ms DESC
                """
            ),
            {"cam": camera_id, "cutoff": cutoff},
        )
        positions = rows.all()

        for r in positions:
            blob = (
                await session.execute(
                    text("SELECT centroid FROM local_centroids WHERE local_id = :lid"),
                    {"lid": r.local_id},
                )
            ).scalar_one_or_none()
            if blob is None:
                continue
            centroid = deserialize_embedding(blob)
            emb_rows = await session.execute(
                text("SELECT embedding FROM local_embeddings WHERE local_id = :lid"),
                {"lid": r.local_id},
            )
            gallery = [deserialize_embedding(b) for (b,) in emb_rows]
            lost[r.local_id] = LostEntry(
                local_id=r.local_id,
                camera_id=camera_id,
                last_floor_x=r.floor_x,
                last_floor_y=r.floor_y,
                last_seen_ts=r.timestamp_ms,
                expiry_batch=current_batch + settings.lost_pool_ttl_batches,
                centroid=centroid,
                gallery=gallery,
            )
    return lost
