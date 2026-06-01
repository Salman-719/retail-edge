"""The persistence seam between identity logic (M3) and the database (M4).

The identity manager never touches SQLAlchemy -- it emits intent through this
port. M3 tests fake it; M4 provides the real PostgreSQL implementation.

Sync/async split (the one M3->M4 contract refinement, documented up front so M4
needs no rework): position writes are *buffered* and therefore synchronous;
embedding/centroid writes hit the DB and are *async*. The manager awaits the
async methods and calls the buffered ones directly. ``flush_temp_positions``
carries ``camera_id`` so pending positions can be written with a non-null camera.
"""

from __future__ import annotations

import uuid
from typing import Protocol

import numpy as np


class PersistencePort(Protocol):
    def append_position(
        self,
        local_id: uuid.UUID,
        camera_id: str,
        timestamp_ms: int,
        floor_x: float,
        floor_y: float,
        zone_id: str | None,
        bbox_confidence: float,
        bbox_area: float,
        bbox_x1: float,
        bbox_y1: float,
        bbox_x2: float,
        bbox_y2: float,
    ) -> None:
        """Buffered; flushed on the 2s timer by the implementation."""
        ...

    def flush_temp_positions(self, local_id: uuid.UUID, camera_id: str, positions: list) -> None:
        """Bulk-insert buffered pending positions under the resolved Local ID."""
        ...

    async def write_embedding(
        self,
        local_id: uuid.UUID,
        camera_id: str,
        captured_ts: int,
        embedding: np.ndarray,
        yolo_confidence: float,
        is_init: bool,
    ) -> None:
        ...

    async def upsert_centroid(
        self, local_id: uuid.UUID, camera_id: str, centroid: np.ndarray, batch_number: int
    ) -> None:
        ...
