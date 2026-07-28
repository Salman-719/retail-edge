"""PostgreSQL persistence — async writes to tracking_history via asyncpg.

No identity logic, no embedding logic, no DDL — pure async DB I/O.
"""
import logging
import uuid

import asyncpg

log = logging.getLogger("iep2.persistence")

_INSERT_SQL = """
INSERT INTO tracking_history
    (store_id, camera_id, local_id, timestamp_ms,
     floor_x, floor_y, zone_id,
     bbox_confidence, bbox_area,
     bbox_x1, bbox_y1, bbox_x2, bbox_y2)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (camera_id, local_id, timestamp_ms) DO NOTHING
"""

_STREAM_RESOLUTION_SQL = """
UPDATE physical_cameras
SET stream_width  = $1,
    stream_height = $2,
    updated_at    = now()
WHERE id = $3::uuid
"""


def _redact(dsn: str) -> str:
    import re
    return re.sub(r"(:)[^:@]+(@)", r"\1***\2", dsn)


class PostgresPersistence:
    def __init__(self, database_url: str, store_id: str, camera_id: str):
        self._database_url = database_url
        self._store_id = uuid.UUID(store_id)
        self._camera_id = camera_id
        self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    async def connect(self) -> None:
        log.info("Creating DB pool  camera=%s  dsn=%s", self._camera_id, _redact(self._database_url))
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=2,           # R6: IEP2 is sequential per-frame; never needs more than 2
            statement_cache_size=0,  # PgBouncer transaction mode: disable prepared-stmt cache
        )
        log.info("DB pool ready  camera=%s", self._camera_id)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            log.info("DB pool closed  camera=%s", self._camera_id)

    async def write_stream_resolution(
        self,
        physical_camera_id: str,
        width: int,
        height: int,
    ) -> None:
        """Write stream resolution to physical_cameras once at IEP2 startup.

        Safe to call multiple times — idempotent UPDATE.
        Logs a warning and continues if the camera row does not exist.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                _STREAM_RESOLUTION_SQL,
                width,
                height,
                physical_camera_id,
            )
        updated = int(result.split()[-1])  # 'UPDATE N' → N
        if updated == 0:
            log.warning(
                "write_stream_resolution: no physical_cameras row found "
                "for camera_id=%s — skipping",
                physical_camera_id,
            )

    async def upsert_local_centroids(
        self,
        records: list[dict],
    ) -> None:
        """UPSERT the appearance embedding store for all active local_ids at batch close.

        records: list of dicts with keys:
            local_id (str UUID), camera_id (str), store_id (str UUID),
            embeddings (bytes), embedding_count (int), quality_scores (bytes),
            updated_at_batch (int)
        UPSERT on local_id primary key — one row per local_id, always the latest
        top-quality embedding heap. Safe to call with an empty list.
        """
        if not records:
            return

        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO local_centroids
                    (local_id, camera_id, store_id,
                     embeddings, embedding_count, quality_scores,
                     updated_at_batch, updated_at)
                VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7, now())
                ON CONFLICT (local_id) DO UPDATE
                    SET embeddings       = EXCLUDED.embeddings,
                        embedding_count  = EXCLUDED.embedding_count,
                        quality_scores   = EXCLUDED.quality_scores,
                        updated_at_batch = EXCLUDED.updated_at_batch,
                        updated_at       = now()
                """,
                [
                    (
                        r["local_id"],
                        r["camera_id"],
                        r["store_id"],
                        r["embeddings"],
                        r["embedding_count"],
                        r["quality_scores"],
                        r["updated_at_batch"],
                    )
                    for r in records
                ],
            )

    async def load_local_embeddings(
        self,
        local_id,
    ) -> tuple[bytes, int, bytes] | None:
        """Load a persisted embedding heap for restart / post-TTL recovery.

        Returns (embeddings_bytes, embedding_count, quality_scores_bytes) or None
        when no row exists. `local_id` is a uuid.UUID.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT embeddings, embedding_count, quality_scores
                FROM local_centroids
                WHERE local_id = $1
                """,
                local_id,
            )
        if row is None or not row["embedding_count"]:
            return None
        return (bytes(row["embeddings"]), int(row["embedding_count"]), bytes(row["quality_scores"]))

    async def insert_detection(
        self,
        local_id: uuid.UUID,
        timestamp_ms: int,
        bbox_confidence: float,
        bbox_area: int,
        floor_x: float | None,
        floor_y: float | None,
        zone_id: uuid.UUID | None,
        bbox_x1: int | None = None,
        bbox_y1: int | None = None,
        bbox_x2: int | None = None,
        bbox_y2: int | None = None,
    ) -> None:
        await self._pool.execute(
            _INSERT_SQL,
            self._store_id,
            self._camera_id,
            local_id,
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
        )
        log.debug(
            "DB write  local_id=%s  ts=%d  conf=%.2f  area=%d",
            local_id, timestamp_ms, bbox_confidence, bbox_area,
        )

    async def insert_detections_batch(self, rows: list[tuple]) -> int:
        """Batch-insert tracking_history rows in ONE round-trip (asyncpg
        executemany) instead of one awaited INSERT per track per frame.

        On a high-latency edge->cloud link (~88 ms RTT over WireGuard), the old
        per-row pattern cost ~rows * 88 ms per window and was the dominant per-
        frame cost (GPU sat idle). Batching the whole window collapses it to a
        single round-trip.

        Each row is the per-detection tuple, store/camera prepended here:
          (local_id, timestamp_ms, bbox_confidence, bbox_area,
           floor_x, floor_y, zone_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
        Returns the number of rows submitted.
        """
        if not rows:
            return 0
        records = [
            (self._store_id, self._camera_id, local_id, ts,
             floor_x, floor_y, zone_id, conf, area, x1, y1, x2, y2)
            for (local_id, ts, conf, area, floor_x, floor_y, zone_id,
                 x1, y1, x2, y2) in rows
        ]
        await self._pool.executemany(_INSERT_SQL, records)
        log.debug("DB batch write  rows=%d  camera=%s", len(records), self._camera_id)
        return len(records)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
