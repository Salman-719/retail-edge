"""Real ``PersistencePort`` against PostgreSQL.

Position writes are buffered and flushed on a wall-clock timer (spec §12.1);
embedding and centroid writes are immediate (low frequency). The buffered
methods are sync (matching the M3 contract); the DB-hitting methods are async.
``maybe_flush`` is driven by the runtime's frame loop, not the manager.
"""

from __future__ import annotations

import uuid
from time import monotonic

import numpy as np
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.db.engine import session_scope
from common.models.iep2_tables import LocalCentroid, LocalEmbedding, TrackingHistory
from common.utils.embeddings import serialize_embedding


class PostgresPersistence:
    """Buffers positions, flushes every ``position_flush_seconds`` or on force."""

    def __init__(self, settings):
        self._s = settings
        self._pos_buffer: list[dict] = []
        self._last_flush = monotonic()

    # ---- positions (buffered, sync) ----

    def append_position(
        self,
        local_id,
        camera_id,
        timestamp_ms,
        floor_x,
        floor_y,
        zone_id,
        bbox_confidence,
        bbox_area,
        bbox_x1,
        bbox_y1,
        bbox_x2,
        bbox_y2,
    ) -> None:
        self._pos_buffer.append(
            dict(
                local_id=local_id, camera_id=camera_id, timestamp_ms=timestamp_ms,
                floor_x=floor_x, floor_y=floor_y, zone_id=zone_id,
                bbox_confidence=bbox_confidence, bbox_area=bbox_area,
                bbox_x1=bbox_x1, bbox_y1=bbox_y1, bbox_x2=bbox_x2, bbox_y2=bbox_y2,
            )
        )

    def flush_temp_positions(self, local_id: uuid.UUID, camera_id: str, positions: list) -> None:
        self._pos_buffer.extend(
            dict(
                local_id=local_id, camera_id=camera_id, timestamp_ms=p.timestamp_ms,
                floor_x=p.floor_x, floor_y=p.floor_y, zone_id=p.zone_id,
                bbox_confidence=p.bbox_confidence, bbox_area=p.bbox_area,
                bbox_x1=p.bbox_x1, bbox_y1=p.bbox_y1, bbox_x2=p.bbox_x2, bbox_y2=p.bbox_y2,
            )
            for p in positions
        )

    async def maybe_flush(self, force: bool = False) -> None:
        """Flush if ``position_flush_seconds`` elapsed or forced (batch end)."""
        if not self._pos_buffer:
            self._last_flush = monotonic()
            return
        if force or (monotonic() - self._last_flush) >= self._s.position_flush_seconds:
            batch, self._pos_buffer = self._pos_buffer, []
            self._last_flush = monotonic()
            async with session_scope() as session:
                await session.execute(insert(TrackingHistory), batch)

    # ---- embeddings (immediate, async) ----

    async def write_embedding(
        self, local_id, camera_id, captured_ts, embedding: np.ndarray, yolo_confidence, is_init
    ) -> None:
        async with session_scope() as session:
            await session.execute(
                pg_insert(LocalEmbedding)
                .values(
                    local_id=local_id, camera_id=camera_id, captured_ts=captured_ts,
                    embedding=serialize_embedding(embedding),
                    yolo_confidence=yolo_confidence, is_init=is_init,
                )
                .on_conflict_do_nothing(index_elements=["local_id", "captured_ts"])
            )

    # ---- centroid (immediate, async, UPSERT) ----

    async def upsert_centroid(self, local_id, camera_id, centroid: np.ndarray, batch_number) -> None:
        async with session_scope() as session:
            stmt = pg_insert(LocalCentroid).values(
                local_id=local_id, camera_id=camera_id,
                centroid=serialize_embedding(centroid), updated_at_batch=batch_number,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["local_id"],
                set_=dict(centroid=stmt.excluded.centroid, updated_at_batch=stmt.excluded.updated_at_batch),
            )
            await session.execute(stmt)
