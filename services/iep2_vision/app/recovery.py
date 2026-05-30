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
            centroid = deserialize_embedding(blob)  # self-describing; dim inferred
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


async def latest_batch_number(camera_id: str, settings=None, redis_client=None) -> int | None:
    """Read the most recent IEP1 ``batch_number`` from ``stream:iep1:{camera_id}``.

    On warm restart, seed ``current_batch`` from this so the LostPool's
    ``expiry_batch`` math aligns with IEP1's batch numbering rather than a locally
    reset counter (IEP2 amendment §5). Returns None if the stream is empty/absent.
    """
    from common.config import get_settings

    s = settings or get_settings()
    client = redis_client
    if client is None:
        import redis.asyncio as redis

        client = redis.from_url(s.REDIS_URL)
    try:
        entries = await client.xrevrange(f"stream:iep1:{camera_id}", count=1)
    except Exception:  # noqa: BLE001 - stream missing / redis down -> no seed
        return None
    if not entries:
        return None
    import json

    _id, fields = entries[0]
    return json.loads(fields[b"manifest"])["batch_number"]
