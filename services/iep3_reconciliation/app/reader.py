"""Reads IEP2's tables for a batch window and classifies every Local ID seen.

Read-only against ``tracking_history`` -- IEP3 never writes IEP2 tables.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text

from common.db.engine import session_scope


@dataclass
class LocalObservation:
    local_id: uuid.UUID
    camera_id: str
    last_floor_x: float
    last_floor_y: float
    last_seen_ts: int
    first_seen_ts: int
    best_confidence: float
    best_bbox_area: float


class BatchReader:
    async def read_window(self, window_start_ms: int, window_end_ms: int) -> list[LocalObservation]:
        async with session_scope() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT local_id, camera_id,
                           MAX(timestamp_ms) AS last_ts,
                           MIN(timestamp_ms) AS first_ts,
                           MAX(bbox_confidence) AS best_conf,
                           MAX(bbox_area) AS best_area,
                           (ARRAY_AGG(floor_x ORDER BY timestamp_ms DESC))[1] AS last_x,
                           (ARRAY_AGG(floor_y ORDER BY timestamp_ms DESC))[1] AS last_y
                    FROM tracking_history
                    WHERE timestamp_ms >= :start AND timestamp_ms < :end
                    GROUP BY local_id, camera_id
                    """
                ),
                {"start": window_start_ms, "end": window_end_ms},
            )
            return [
                LocalObservation(
                    local_id=r.local_id,
                    camera_id=r.camera_id,
                    last_floor_x=r.last_x,
                    last_floor_y=r.last_y,
                    last_seen_ts=r.last_ts,
                    first_seen_ts=r.first_ts,
                    best_confidence=r.best_conf or 0.0,
                    best_bbox_area=r.best_area or 0.0,
                )
                for r in rows
            ]
