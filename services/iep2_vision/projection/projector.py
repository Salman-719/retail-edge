"""Floor projection — maps pixel bbox foot points to world coordinates.

Homography and zone data are loaded once from PostgreSQL at startup via the
asyncpg pool that PostgresPersistence already owns. No second connection opened.
"""
import json
import logging
import uuid

import asyncpg
import numpy as np
from shapely.geometry import Point, Polygon

log = logging.getLogger("iep2.projector")

_HOMOGRAPHY_SQL = """
SELECT c.homography_matrix
FROM calibrations c
WHERE c.camera_config_id = $1
  AND c.is_current = true
  AND c.status IN ('ok', 'verified')
  AND c.method = 'homography'
LIMIT 1
"""

_ZONES_SQL = """
SELECT z.id, z.points
FROM zones z
JOIN store_config_versions scv ON scv.id = z.version_id
JOIN camera_configs cc ON cc.version_id = scv.id
WHERE cc.id = $1
  AND scv.status = 'active'
"""


def _parse_homography(raw) -> np.ndarray:
    """Normalize JSONB homography to float64 (3,3) regardless of storage format."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    arr = np.array(raw, dtype=np.float64)
    if arr.shape == (9,):
        arr = arr.reshape(3, 3)
    if arr.shape != (3, 3):
        raise ValueError(f"Unexpected homography shape {arr.shape}; expected (3,3) or (9,)")
    return arr


def _parse_points(raw) -> list:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


class FloorProjector:
    def __init__(self):
        self._H: np.ndarray | None = None
        self._zones: list[tuple[uuid.UUID, Polygon]] = []

    async def load(self, pool: asyncpg.Pool, camera_config_id: uuid.UUID) -> None:
        """Load homography matrix and zone polygons. Uses the shared asyncpg pool."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_HOMOGRAPHY_SQL, camera_config_id)
            if row is None or row["homography_matrix"] is None:
                log.warning(
                    "No active homography calibration found  camera_config_id=%s  "
                    "— floor_x/floor_y will be NULL",
                    camera_config_id,
                )
                self._H = None
            else:
                self._H = _parse_homography(row["homography_matrix"])
                log.info("Homography loaded  camera_config_id=%s", camera_config_id)

            zone_rows = await conn.fetch(_ZONES_SQL, camera_config_id)
            self._zones = []
            for r in zone_rows:
                points = _parse_points(r["points"])
                self._zones.append((r["id"], Polygon(points)))
            log.info(
                "Zones loaded  count=%d  camera_config_id=%s",
                len(self._zones), camera_config_id,
            )

    def project(self, x1: int, y1: int, x2: int, y2: int) -> tuple[float, float] | None:
        """Project bbox foot point to floor coordinates via homography.

        Foot point is the bottom-centre of the bounding box.
        Returns (floor_x, floor_y) in world units, or None if no homography loaded.
        """
        if self._H is None:
            return None
        px = (x1 + x2) / 2.0
        py = float(y2)
        src = np.array([px, py, 1.0], dtype=np.float64)
        dst = self._H @ src
        return float(dst[0] / dst[2]), float(dst[1] / dst[2])

    def zone_of(self, floor_x: float, floor_y: float) -> uuid.UUID | None:
        """Return the UUID of the first zone polygon containing the floor point."""
        if not self._zones:
            return None
        pt = Point(floor_x, floor_y)
        for zone_id, polygon in self._zones:
            if polygon.contains(pt):
                return zone_id
        return None
