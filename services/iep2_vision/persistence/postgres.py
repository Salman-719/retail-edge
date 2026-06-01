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
     bbox_confidence, bbox_area)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
            self._database_url, min_size=1, max_size=5
        )
        log.info("DB pool ready  camera=%s", self._camera_id)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            log.info("DB pool closed  camera=%s", self._camera_id)

    async def insert_detection(
        self,
        local_id: uuid.UUID,
        timestamp_ms: int,
        bbox_confidence: float,
        bbox_area: int,
        floor_x: float | None,
        floor_y: float | None,
        zone_id: uuid.UUID | None,
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
        )
        log.debug(
            "DB write  local_id=%s  ts=%d  conf=%.2f  area=%d",
            local_id, timestamp_ms, bbox_confidence, bbox_area,
        )

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
