"""IEP5 persistence — preflight + context reads. IEP5 reads only here; the
analytics WRITES happen inside the pipeline transaction via the aggregators.
"""
from __future__ import annotations

import uuid
from datetime import date

import asyncpg

from app.persistence import queries as q


class AnalyticsRepository:
    def __init__(self, pool: asyncpg.Pool, store_id: str) -> None:
        self._pool = pool
        self._store_id = uuid.UUID(store_id)

    @property
    def store_id(self) -> uuid.UUID:
        return self._store_id

    # ── Preflight ────────────────────────────────────────────────────────────

    async def count_open_visits(self) -> int:
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval(q.COUNT_OPEN_VISITS, self._store_id) or 0)

    async def count_active_person_state(self) -> int:
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval(q.COUNT_ACTIVE_PERSON_STATE, self._store_id) or 0)

    async def count_gth_in_window(self, start_ms: int, end_ms: int) -> int:
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval(
                q.COUNT_GTH_IN_WINDOW, self._store_id, start_ms, end_ms) or 0)

    async def daily_summary_exists(self, shift_date: date) -> bool:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(q.COUNT_EXISTING_DAILY, self._store_id, shift_date)
        return int(n or 0) > 0

    # ── Context ──────────────────────────────────────────────────────────────

    async def shift_bounds(self, day_start_ms: int, day_end_ms: int) -> tuple[int | None, int | None]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(q.SHIFT_BOUNDS, self._store_id, day_start_ms, day_end_ms)
        if row is None or row["shift_start_ms"] is None:
            return None, None
        return int(row["shift_start_ms"]), int(row["shift_end_ms"])

    async def active_version_origin(self) -> tuple[uuid.UUID | None, float, float]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(q.ACTIVE_VERSION_ORIGIN, self._store_id)
        if row is None:
            return None, 0.0, 0.0
        return row["version_id"], float(row["origin_x"]), float(row["origin_y"])
