"""Floor projection — maps pixel bbox foot points to world coordinates.

Homography and zone data are loaded once from PostgreSQL at startup via the
asyncpg pool that PostgresPersistence already owns. No second connection opened.
"""
import json
import logging
import uuid
from collections import namedtuple

import asyncpg
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points

log = logging.getLogger("iep2.projector")

# Returned by project_and_clamp(). clamped=True means the projected foot point
# was outside the floor boundary and was snapped to the nearest boundary edge.
ProjectionResult = namedtuple("ProjectionResult", ["x", "y", "clamped"])

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

_BOUNDARY_SQL = """
SELECT fp.boundary_polygon,
       fp.world_x_min, fp.world_x_max,
       fp.world_y_min, fp.world_y_max
FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN floor_plans fp             ON fp.version_id = scv.id
                               AND fp.section_id = cc.section_id
WHERE cc.id = $1
  AND scv.status = 'active'
LIMIT 1
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
        self._boundary: Polygon | None = None
        self._world_bounds: tuple[float, float, float, float] | None = None
        self._camera_config_id: uuid.UUID | None = None
        self._clamp_count: int = 0

    async def load(self, pool: asyncpg.Pool, camera_config_id: uuid.UUID) -> None:
        """Load homography matrix, zone polygons, and floor boundary. Uses the shared asyncpg pool."""
        self._camera_config_id = camera_config_id
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

            fp_row = await conn.fetchrow(_BOUNDARY_SQL, camera_config_id)
            if fp_row is None or fp_row["boundary_polygon"] is None:
                log.info(
                    "No floor boundary polygon found  camera_config_id=%s  "
                    "— boundary enforcement disabled",
                    camera_config_id,
                )
                self._boundary = None
                self._world_bounds = None
            else:
                pts = _parse_points(fp_row["boundary_polygon"])
                self._boundary = Polygon(pts)
                self._world_bounds = (
                    fp_row["world_x_min"],
                    fp_row["world_x_max"],
                    fp_row["world_y_min"],
                    fp_row["world_y_max"],
                )
                log.info(
                    "Floor boundary loaded  camera_config_id=%s  world_bounds=%s",
                    camera_config_id, self._world_bounds,
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

    def project_and_clamp(self, x1: int, y1: int, x2: int, y2: int) -> "ProjectionResult | None":
        """Project bbox foot point with boundary enforcement.

        Returns:
          None               — no homography loaded (HOMOGRAPHY_ABSENT).
          ProjectionResult(x, y, clamped=False) — projected point is inside boundary
                                                   (or no boundary loaded).
          ProjectionResult(x, y, clamped=True)  — projected point was outside boundary
                                                   and was snapped to the nearest edge.
        """
        if self._H is None:
            return None

        px = (x1 + x2) / 2.0
        py = float(y2)
        src = np.array([px, py, 1.0], dtype=np.float64)
        dst = self._H @ src
        fx = float(dst[0] / dst[2])
        fy = float(dst[1] / dst[2])

        if self._boundary is None:
            return ProjectionResult(fx, fy, clamped=False)

        pt = Point(fx, fy)
        if self._boundary.contains(pt):
            return ProjectionResult(fx, fy, clamped=False)

        # Out of bounds — snap to nearest point on boundary exterior.
        nearest = nearest_points(self._boundary.exterior, pt)[0]
        self._clamp_count += 1
        if self._clamp_count % 100 == 0:
            log.debug(
                "project_and_clamp: %d out-of-bounds projections clamped  camera_config_id=%s",
                self._clamp_count, self._camera_config_id,
            )
        return ProjectionResult(nearest.x, nearest.y, clamped=True)

    def zone_of(self, floor_x: float, floor_y: float) -> uuid.UUID | None:
        """Return the UUID of the first zone polygon containing the floor point."""
        if not self._zones:
            return None
        pt = Point(floor_x, floor_y)
        for zone_id, polygon in self._zones:
            if polygon.contains(pt):
                return zone_id
        return None


# ---------------------------------------------------------------------------
# Standalone smoke tests: python projection/projector.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import math

    # Minimal 3×3 identity-like homography: pixel → floor 1:1 at scale 0.01 m/px
    # H maps (px, py, 1) → (px*0.01, py*0.01, 1)
    H = np.array([
        [0.01, 0.0,  0.0],
        [0.0,  0.01, 0.0],
        [0.0,  0.0,  1.0],
    ], dtype=np.float64)

    # Square boundary: 0..5 m × 0..5 m
    square = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])

    proj = FloorProjector()
    proj._H = H
    proj._boundary = square

    # ── Test 1: H is None → None ──────────────────────────────────────────────
    proj_none = FloorProjector()
    result = proj_none.project_and_clamp(0, 0, 100, 200)
    assert result is None, f"H=None must return None, got {result}"
    print("[1] H is None -> None OK")

    # ── Test 2: boundary is None → unclamped result ───────────────────────────
    proj_no_boundary = FloorProjector()
    proj_no_boundary._H = H
    # bbox: x1=100, y1=0, x2=200, y2=300 → foot=(150, 300) → floor=(1.5, 3.0)
    result = proj_no_boundary.project_and_clamp(100, 0, 200, 300)
    assert result is not None
    assert result.clamped is False, "No boundary must return clamped=False"
    assert abs(result.x - 1.5) < 1e-9
    assert abs(result.y - 3.0) < 1e-9
    print(f"[2] boundary=None -> ProjectionResult(x={result.x}, y={result.y}, clamped={result.clamped}) OK")

    # ── Test 3: inside boundary → unclamped ───────────────────────────────────
    # foot=(250, 250) → floor=(2.5, 2.5) — inside 0..5 square
    result = proj.project_and_clamp(200, 0, 300, 250)
    assert result is not None
    assert result.clamped is False
    assert abs(result.x - 2.5) < 1e-9
    assert abs(result.y - 2.5) < 1e-9
    print(f"[3] inside boundary -> ProjectionResult(x={result.x:.2f}, y={result.y:.2f}, clamped={result.clamped}) OK")

    # ── Test 4: outside boundary → clamped, coords on boundary ───────────────
    # foot=(1000, 1000) → floor=(10.0, 10.0) — outside 0..5 square
    result = proj.project_and_clamp(900, 0, 1100, 1000)
    assert result is not None
    assert result.clamped is True, f"Out-of-bounds must return clamped=True, got {result}"
    # Nearest point on boundary of 0..5 square from (10,10) is (5,5)
    assert abs(result.x - 5.0) < 1e-9, f"Expected x=5.0, got {result.x}"
    assert abs(result.y - 5.0) < 1e-9, f"Expected y=5.0, got {result.y}"
    print(f"[4] outside boundary -> clamped to ({result.x:.1f}, {result.y:.1f}) OK")

    # ── Test 5: clamped=True is a real bool ───────────────────────────────────
    assert isinstance(result.clamped, bool), f"clamped must be bool, got {type(result.clamped)}"
    print("[5] clamped is bool OK")

    # ── Test 6: rate-limited logging counter increments correctly ─────────────
    proj2 = FloorProjector()
    proj2._H = H
    proj2._boundary = square
    for _ in range(99):
        proj2.project_and_clamp(900, 0, 1100, 1000)
    assert proj2._clamp_count == 99
    proj2.project_and_clamp(900, 0, 1100, 1000)  # 100th — triggers log
    assert proj2._clamp_count == 100
    print(f"[6] clamp counter = {proj2._clamp_count} OK")

    print("\nsmoke tests passed")
