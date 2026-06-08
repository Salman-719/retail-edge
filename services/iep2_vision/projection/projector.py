"""Floor projection — maps pixel bbox foot points to world coordinates.

Homography and zone data are loaded once from PostgreSQL at startup via the
asyncpg pool that PostgresPersistence already owns. No second connection opened.
"""
import json
import logging
import uuid
from collections import namedtuple

import asyncpg
import cv2
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points

log = logging.getLogger("iep2.projector")

# Returned by project_and_clamp(). clamped=True means the projected foot point
# was outside the floor boundary and was snapped to the nearest boundary edge.
ProjectionResult = namedtuple("ProjectionResult", ["x", "y", "clamped"])

# Loads whichever calibration is current, regardless of method. The mode switch
# in load() decides how project() interprets it. Only one row can be current per
# config (partial unique index), so LIMIT 1 is unambiguous.
_CALIBRATION_SQL = """
SELECT c.method,
       c.homography_matrix,
       c.intrinsic_matrix,
       c.dist_coeffs,
       c.rotation_vector,
       c.translation_vector,
       c.correspondences
FROM calibrations c
WHERE c.camera_config_id = $1
  AND c.is_current = true
  AND c.status IN ('ok', 'verified')
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
       fp.world_y_min, fp.world_y_max,
       fp.origin_x, fp.origin_y, fp.pixels_per_meter
FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN floor_plans fp             ON fp.version_id = scv.id
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


def _parse_matrix(raw) -> np.ndarray:
    """Normalize a JSONB matrix/vector to a float64 numpy array (any shape)."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    return np.array(raw, dtype=np.float64)


class FloorProjector:
    def __init__(self):
        # mode: 'homography' | 'pnp' | 'tps' | None
        self._mode: str | None = None
        # Homography mode state.
        self._H: np.ndarray | None = None
        # PnP mode state (all precomputed in load() — never in project()).
        self._camera_matrix: np.ndarray | None = None
        self._dist_coeffs: np.ndarray | None = None
        self._R: np.ndarray | None = None
        self._tvec: np.ndarray | None = None
        self._camera_center: np.ndarray | None = None
        self._K_inv: np.ndarray | None = None
        # TPS mode state (RBFInterpolators fitted at load time).
        self._rbf_x = None
        self._rbf_y = None

        self._zones: list[tuple[uuid.UUID, Polygon]] = []
        self._boundary: Polygon | None = None
        self._world_bounds: tuple[float, float, float, float] | None = None
        # Floor plan pixel→meter conversion (homography mode only).
        # Homography maps camera pixels → floor plan image pixels. These three
        # values convert those pixel coords to world meters:
        #   world_x = (px - origin_x) / pixels_per_meter
        #   world_y = (py - origin_y) / pixels_per_meter
        self._fp_origin_x: float | None = None
        self._fp_origin_y: float | None = None
        self._fp_ppm: float | None = None
        self._camera_config_id: uuid.UUID | None = None
        self._clamp_count: int = 0

    def _load_calibration(self, row) -> None:
        """Set projection mode and precompute state from a calibration row."""
        # Reset all calibration state; zones/boundary are loaded separately.
        self._mode = None
        self._H = None
        self._camera_matrix = self._dist_coeffs = None
        self._R = self._tvec = self._camera_center = self._K_inv = None
        self._rbf_x = None
        self._rbf_y = None

        if row is None:
            log.warning(
                "No active calibration found  camera_config_id=%s  "
                "— floor_x/floor_y will be NULL",
                self._camera_config_id,
            )
            return

        method = row["method"]
        if method == "pnp":
            try:
                K = _parse_matrix(row["intrinsic_matrix"]).reshape(3, 3)
                dist = _parse_matrix(row["dist_coeffs"]).reshape(-1, 1)
                rvec = _parse_matrix(row["rotation_vector"]).reshape(3, 1)
                tvec = _parse_matrix(row["translation_vector"]).reshape(3, 1)
                R, _ = cv2.Rodrigues(rvec)
                self._camera_matrix = K
                self._dist_coeffs = dist
                self._R = R
                self._tvec = tvec
                self._camera_center = (-R.T @ tvec).flatten()
                self._K_inv = np.linalg.inv(K)
                self._mode = "pnp"
                log.info("PnP calibration loaded  camera_config_id=%s", self._camera_config_id)
            except Exception as exc:
                log.error(
                    "Failed to load PnP calibration  camera_config_id=%s: %s  "
                    "— floor_x/floor_y will be NULL",
                    self._camera_config_id, exc,
                )
                self._mode = None
        elif method == "homography":
            if row["homography_matrix"] is None:
                log.warning(
                    "Homography calibration has no matrix  camera_config_id=%s",
                    self._camera_config_id,
                )
            else:
                self._H = _parse_homography(row["homography_matrix"])
                self._mode = "homography"
                log.info("Homography loaded  camera_config_id=%s", self._camera_config_id)
        elif method == "tps":
            try:
                import numpy as _np
                from scipy.interpolate import RBFInterpolator

                raw_corr = row["correspondences"]
                if isinstance(raw_corr, str):
                    raw_corr = json.loads(raw_corr)
                if not raw_corr or len(raw_corr) < 4:
                    log.warning(
                        "TPS calibration has too few control points  camera_config_id=%s",
                        self._camera_config_id,
                    )
                    return
                frame_pts = _np.array([[c["frame_px"], c["frame_py"]] for c in raw_corr])
                world_pts = _np.array([[c["world_x_m"], c["world_y_m"]] for c in raw_corr])
                self._rbf_x = RBFInterpolator(frame_pts, world_pts[:, 0], kernel="thin_plate_spline", smoothing=0)
                self._rbf_y = RBFInterpolator(frame_pts, world_pts[:, 1], kernel="thin_plate_spline", smoothing=0)
                self._mode = "tps"
                log.info(
                    "TPS calibration loaded  camera_config_id=%s  control_points=%d",
                    self._camera_config_id, len(raw_corr),
                )
            except Exception as exc:
                log.error(
                    "Failed to load TPS calibration  camera_config_id=%s: %s  "
                    "— floor_x/floor_y will be NULL",
                    self._camera_config_id, exc,
                )
                self._mode = None
        else:
            log.warning(
                "Unsupported calibration method=%s  camera_config_id=%s",
                method, self._camera_config_id,
            )

    async def load(self, pool: asyncpg.Pool, camera_config_id: uuid.UUID) -> None:
        """Load current calibration (PnP or homography), zones, and floor boundary."""
        self._camera_config_id = camera_config_id
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_CALIBRATION_SQL, camera_config_id)
            self._load_calibration(row)

            # Load floor plan scale first — zone conversion depends on it.
            fp_row = await conn.fetchrow(_BOUNDARY_SQL, camera_config_id)
            if fp_row is None or fp_row["boundary_polygon"] is None:
                log.info(
                    "No floor boundary polygon found  camera_config_id=%s  "
                    "— boundary enforcement disabled",
                    camera_config_id,
                )
                self._boundary = None
                self._world_bounds = None
                self._fp_origin_x = None
                self._fp_origin_y = None
                self._fp_ppm = None
            else:
                pts = _parse_points(fp_row["boundary_polygon"])
                self._fp_origin_x = fp_row["origin_x"]
                self._fp_origin_y = fp_row["origin_y"]
                self._fp_ppm      = fp_row["pixels_per_meter"]
                # boundary_polygon is stored in world metres (EEP _px_to_world),
                # the same space as the projected floor_x/floor_y — use it as-is.
                # (origin/ppm are still needed below for the homography px→metre
                # projection, hence they are retained above.)
                self._boundary = Polygon(pts)
                self._world_bounds = (
                    fp_row["world_x_min"],
                    fp_row["world_x_max"],
                    fp_row["world_y_min"],
                    fp_row["world_y_max"],
                )
                log.info(
                    "Floor boundary loaded  camera_config_id=%s  world_bounds=%s  "
                    "origin=(%s,%s)  ppm=%s",
                    camera_config_id, self._world_bounds,
                    self._fp_origin_x, self._fp_origin_y, self._fp_ppm,
                )

            zone_rows = await conn.fetch(_ZONES_SQL, camera_config_id)
            self._zones = []
            for r in zone_rows:
                points = _parse_points(r["points"])
                # zones.points are stored in world metres (EEP _px_to_world), the
                # same space as the projected floor_x/floor_y — use them as-is.
                # (Previously these were wrongly divided by ppm as if pixels,
                # which made zone_of() never match → tracking_history.zone_id NULL.)
                self._zones.append((r["id"], Polygon(points)))
            log.info(
                "Zones loaded  count=%d  camera_config_id=%s",
                len(self._zones), camera_config_id,
            )

    def _project_foot(self, x1: int, y1: int, x2: int, y2: int) -> tuple[float, float] | None:
        """Project the bbox bottom-centre foot point to floor coords.

        Mode-aware. Returns (floor_x, floor_y) or None. Contains no matrix
        inversion — all heavy precompute happens in load().
        """
        # Bottom-centre is the ONLY valid projection point.
        u = (x1 + x2) / 2.0
        v = float(y2)

        if self._mode == "homography":
            src = np.array([u, v, 1.0], dtype=np.float64)
            dst = self._H @ src
            px = float(dst[0] / dst[2])
            py = float(dst[1] / dst[2])
            # Homography maps camera pixels → floor plan image pixels.
            # Convert to world meters using the floor plan scale if available.
            if (self._fp_ppm is not None and self._fp_ppm > 0
                    and self._fp_origin_x is not None
                    and self._fp_origin_y is not None):
                return (
                    (px - self._fp_origin_x) / self._fp_ppm,
                    (py - self._fp_origin_y) / self._fp_ppm,
                )
            # No floor plan scale configured — return raw pixel coords.
            return px, py

        if self._mode == "pnp":
            return self._project_pnp_ray(u, v)

        if self._mode == "tps":
            return self._project_tps(u, v)

        return None

    def _project_pnp_ray(self, u: float, v: float) -> tuple[float, float] | None:
        """Ray-plane intersection: cast pixel (u, v) onto the Z=0 floor plane."""
        # Undistort even when dist_coeffs are zero — keeps the path consistent
        # for when real distortion values are added later.
        pixel = np.array([[[u, v]]], dtype=np.float64)
        undistorted = cv2.undistortPoints(
            pixel, self._camera_matrix, self._dist_coeffs, P=self._camera_matrix
        )
        u_corr = undistorted[0][0][0]
        v_corr = undistorted[0][0][1]

        # Ray direction in world coordinates.
        point_cam = self._K_inv @ np.array([u_corr, v_corr, 1.0], dtype=np.float64)
        ray_dir = self._R.T @ point_cam
        norm = np.linalg.norm(ray_dir)
        if norm < 1e-12:
            return None
        ray_dir = ray_dir / norm

        cam_center = self._camera_center  # (3,)

        # Ray parallel to floor — no intersection.
        if abs(ray_dir[2]) < 1e-6:
            return None

        t = -cam_center[2] / ray_dir[2]

        # Intersection behind the camera — point was above the camera.
        if t < 0:
            return None

        floor_x = cam_center[0] + t * ray_dir[0]
        floor_y = cam_center[1] + t * ray_dir[1]
        return float(floor_x), float(floor_y)

    def _project_tps(self, u: float, v: float) -> tuple[float, float] | None:
        """Project via TPS RBFInterpolators. Returns (world_x_m, world_y_m) or None."""
        try:
            import numpy as _np
            query = _np.array([[u, v]])
            return float(self._rbf_x(query)[0]), float(self._rbf_y(query)[0])
        except Exception as exc:
            log.warning(
                "TPS projection failed  camera_config_id=%s: %s",
                self._camera_config_id, exc,
            )
            return None

    def project(self, x1: int, y1: int, x2: int, y2: int) -> tuple[float, float] | None:
        """Project bbox foot point to floor coordinates.

        Foot point is the bottom-centre of the bounding box.
        Returns (floor_x, floor_y) in world units, or None if no calibration.
        """
        return self._project_foot(x1, y1, x2, y2)

    def project_and_clamp(self, x1: int, y1: int, x2: int, y2: int) -> "ProjectionResult | None":
        """Project bbox foot point with boundary enforcement.

        Returns:
          None               — no calibration loaded (projection absent).
          ProjectionResult(x, y, clamped=False) — projected point is inside boundary
                                                   (or no boundary loaded).
          ProjectionResult(x, y, clamped=True)  — projected point was outside boundary
                                                   and was snapped to the nearest edge.
        """
        foot = self._project_foot(x1, y1, x2, y2)
        if foot is None:
            return None
        fx, fy = foot

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
    proj._mode = 'homography'
    proj._boundary = square

    # ── Test 1: H is None → None ──────────────────────────────────────────────
    proj_none = FloorProjector()
    result = proj_none.project_and_clamp(0, 0, 100, 200)
    assert result is None, f"H=None must return None, got {result}"
    print("[1] H is None -> None OK")

    # ── Test 2: boundary is None → unclamped result ───────────────────────────
    proj_no_boundary = FloorProjector()
    proj_no_boundary._H = H
    proj_no_boundary._mode = 'homography'
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
    proj2._mode = 'homography'
    proj2._boundary = square
    for _ in range(99):
        proj2.project_and_clamp(900, 0, 1100, 1000)
    assert proj2._clamp_count == 99
    proj2.project_and_clamp(900, 0, 1100, 1000)  # 100th — triggers log
    assert proj2._clamp_count == 100
    print(f"[6] clamp counter = {proj2._clamp_count} OK")

    print("\nsmoke tests passed")
