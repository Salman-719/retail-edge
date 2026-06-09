"""Camera → zone coverage geometry.

Computes which floor zones a calibrated camera can observe, so IEP3 can build
its cross-camera overlap graph (only cameras that share a zone are ever
compared). Pure geometry — no DB. The DB glue lives in app/core/coverage.py.

Approach
--------
A camera's field of view on the floor is estimated by *grid-sampling* the image
frame, projecting each sample pixel onto the floor via the camera's current
calibration, discarding projections that are invalid (behind the camera, at the
horizon, or outside the floor boundary), and taking the convex hull of the
surviving points as the camera's floor **footprint**. Grid sampling (rather than
just projecting the 4 frame corners) is robust to perspective views, where the
top of the frame projects to the horizon / infinity.

Coordinate space
----------------
Everything is computed in **world metres** — the coordinate system that
`tracking_history.floor_x/y` and `zones.points` already use (both written via
EEP's `_px_to_world`). PnP and TPS project to metres directly; a homography maps
camera pixels to floor-plan image pixels, which are then converted to metres via
(px - origin) / pixels_per_metre — the same transform as FloorProjector. The
floor-plan boundary fallback (image rectangle, in pixels) is likewise converted.
"""
from __future__ import annotations

import logging

import numpy as np
from shapely.geometry import Point, Polygon

log = logging.getLogger("eep.coverage")

# Sampling density across the frame: (GRID+1)^2 points. 16 → 289 samples,
# enough to capture FOV shape without being expensive (runs at activation only).
DEFAULT_GRID = 16

# A zone counts as "covered" only when the footprint overlaps more than this
# fraction of its area — filters out hull slivers grazing a zone edge.
MIN_COVERAGE_FRACTION = 1e-3


# =============================================================================
# Calibration — a parsed, DB-agnostic view used by project_pixel()
# =============================================================================

class CameraCalibration:
    """Parsed calibration sufficient to project a pixel onto the floor plan.

    Built by the DB layer from a `calibrations` row plus the floor-plan scale.
    Only the fields for `method` need be populated. For pnp/tps the floor-plan
    scale (ppm, origin_x, origin_y) is required to map world metres back into
    floor-plan pixels; for homography it is unused.
    """

    def __init__(
        self,
        method: str,
        *,
        homography: np.ndarray | None = None,
        camera_matrix: np.ndarray | None = None,
        dist_coeffs: np.ndarray | None = None,
        rotation_vector: np.ndarray | None = None,
        translation_vector: np.ndarray | None = None,
        correspondences: list | None = None,
        ppm: float | None = None,
        origin_x: float | None = None,
        origin_y: float | None = None,
    ) -> None:
        self.method = method
        self._ppm = ppm
        self._origin_x = origin_x
        self._origin_y = origin_y

        # Homography mode.
        self._H = homography

        # PnP mode — precompute the same intermediates FloorProjector uses.
        self._R = None
        self._K_inv = None
        self._camera_matrix = camera_matrix
        self._dist_coeffs = dist_coeffs
        self._camera_center = None
        if method == "pnp" and camera_matrix is not None:
            import cv2

            rvec = np.asarray(rotation_vector, dtype=np.float64).reshape(3, 1)
            tvec = np.asarray(translation_vector, dtype=np.float64).reshape(3, 1)
            R, _ = cv2.Rodrigues(rvec)
            self._R = R
            self._camera_center = (-R.T @ tvec).flatten()
            self._K_inv = np.linalg.inv(np.asarray(camera_matrix, dtype=np.float64))

        # TPS mode — fit the RBF interpolators once.
        self._rbf_x = None
        self._rbf_y = None
        if method == "tps" and correspondences:
            from scipy.interpolate import RBFInterpolator

            frame_pts = np.array([[c["frame_px"], c["frame_py"]] for c in correspondences])
            world_pts = np.array([[c["world_x_m"], c["world_y_m"]] for c in correspondences])
            self._rbf_x = RBFInterpolator(frame_pts, world_pts[:, 0], kernel="thin_plate_spline", smoothing=0)
            self._rbf_y = RBFInterpolator(frame_pts, world_pts[:, 1], kernel="thin_plate_spline", smoothing=0)

    # ── projection ────────────────────────────────────────────────────────────

    def project_pixel(self, u: float, v: float) -> tuple[float, float] | None:
        """Project image pixel (u, v) onto the floor plan in floor-plan pixels.

        Returns None when the pixel does not map to a valid floor point.
        """
        if self.method == "homography":
            if self._H is None:
                return None
            dst = self._H @ np.array([u, v, 1.0], dtype=np.float64)
            if abs(dst[2]) < 1e-12:
                return None
            # Homography maps frame px → floor-plan map px; convert map px →
            # world metres so it matches zones/boundary (stored in metres).
            return self._map_px_to_world(float(dst[0] / dst[2]), float(dst[1] / dst[2]))

        if self.method == "pnp":
            return self._project_pnp(u, v)   # already world metres

        if self.method == "tps":
            return self._project_tps(u, v)   # already world metres

        return None

    def _project_pnp(self, u: float, v: float) -> tuple[float, float] | None:
        import cv2

        pixel = np.array([[[u, v]]], dtype=np.float64)
        undist = cv2.undistortPoints(pixel, self._camera_matrix, self._dist_coeffs, P=self._camera_matrix)
        point_cam = self._K_inv @ np.array([undist[0][0][0], undist[0][0][1], 1.0], dtype=np.float64)
        ray_dir = self._R.T @ point_cam
        norm = np.linalg.norm(ray_dir)
        if norm < 1e-12 or abs(ray_dir[2]) < 1e-6:
            return None
        ray_dir = ray_dir / norm
        t = -self._camera_center[2] / ray_dir[2]
        if t < 0:
            return None
        return (
            float(self._camera_center[0] + t * ray_dir[0]),
            float(self._camera_center[1] + t * ray_dir[1]),
        )

    def _project_tps(self, u: float, v: float) -> tuple[float, float] | None:
        if self._rbf_x is None:
            return None
        q = np.array([[u, v]])
        return float(self._rbf_x(q)[0]), float(self._rbf_y(q)[0])

    def _map_px_to_world(self, px: float, py: float) -> tuple[float, float] | None:
        """Floor-plan image pixels → world metres: (px - origin) / ppm.

        Same transform as EEP's _px_to_world / FloorProjector. Requires the
        floor-plan scale; returns None if it is missing (homography is unusable
        without it).
        """
        if self._ppm is None or self._ppm <= 0 or self._origin_x is None or self._origin_y is None:
            return None
        return ((px - self._origin_x) / self._ppm, (py - self._origin_y) / self._ppm)


def frame_bounds_from_correspondences(corr) -> tuple[float, float, float, float] | None:
    """Frame-pixel bounding box (umin, umax, vmin, vmax) of a calibration's
    control points, or None.

    Handles both TPS correspondences ({"frame_px","frame_py",...}) and homography
    correspondences ({"pixel":[x,y],"world":[X,Y]}). Used to bound coverage
    sampling to the calibrated region, independent of the camera's resolution.
    """
    us: list[float] = []
    vs: list[float] = []
    for c in corr or []:
        if "frame_px" in c and "frame_py" in c:
            us.append(float(c["frame_px"])); vs.append(float(c["frame_py"]))
        elif isinstance(c.get("pixel"), (list, tuple)) and len(c["pixel"]) >= 2:
            us.append(float(c["pixel"][0])); vs.append(float(c["pixel"][1]))
    if len(us) < 3 or max(us) <= min(us) or max(vs) <= min(vs):
        return None
    return (min(us), max(us), min(vs), max(vs))


# =============================================================================
# Footprint + coverage
# =============================================================================

def camera_floor_footprint(
    calib: CameraCalibration,
    frame_width: int,
    frame_height: int,
    boundary: Polygon | None = None,
    grid: int = DEFAULT_GRID,
    sample_region: tuple[float, float, float, float] | None = None,
) -> Polygon | None:
    """Estimate the camera's floor footprint as a convex-hull polygon.

    Grid-samples the camera frame, projects each pixel, keeps finite projections
    that fall inside `boundary` (if given), and returns their convex hull.

    sample_region (umin, umax, vmin, vmax), in frame pixels, bounds the sampling
    to the region the calibration actually covers (its control points). When
    given, frame_width/height are ignored — this removes the dependency on the
    camera's true resolution and avoids extrapolating a homography/TPS far beyond
    its control points. When None, the full frame is sampled.

    Returns None when fewer than 3 valid points survive (no usable footprint).
    """
    if sample_region is not None:
        umin, umax, vmin, vmax = sample_region
    else:
        umin, umax, vmin, vmax = 0.0, float(frame_width), 0.0, float(frame_height)
    if umax <= umin or vmax <= vmin or grid < 1:
        return None

    pts: list[tuple[float, float]] = []
    for i in range(grid + 1):
        u = umin + (umax - umin) * i / grid
        for j in range(grid + 1):
            v = vmin + (vmax - vmin) * j / grid
            p = calib.project_pixel(u, v)
            if p is None or not (np.isfinite(p[0]) and np.isfinite(p[1])):
                continue
            if boundary is not None and not boundary.contains(Point(p)):
                continue
            pts.append(p)

    if len(pts) < 3:
        return None

    # Polygon(pts).convex_hull is order-independent and avoids shapely's
    # MultiPoint collection constructor (broken under some shapely/numpy combos).
    hull = Polygon(pts).convex_hull
    # Degenerate (collinear) hulls have zero area and cannot cover a zone.
    if not isinstance(hull, Polygon) or hull.is_empty or hull.area <= 0:
        return None
    return hull


def zone_coverages(
    footprint: Polygon | None,
    zones: list[tuple[object, Polygon]],
    min_fraction: float = MIN_COVERAGE_FRACTION,
) -> list[tuple[object, float]]:
    """Return [(zone_id, coverage_percent)] for zones the footprint overlaps.

    coverage_percent ∈ (min_fraction, 1.0] is the fraction of the zone's area
    inside the footprint. Zones with no meaningful overlap are omitted, so the
    result set is exactly the camera's covered zones.
    """
    out: list[tuple[object, float]] = []
    if footprint is None or footprint.is_empty:
        return out

    for zone_id, poly in zones:
        if poly is None or poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)  # fix self-intersections
        if poly.is_empty or poly.area <= 0:
            continue
        inter = footprint.intersection(poly)
        if inter.is_empty:
            continue
        frac = inter.area / poly.area
        if frac > min_fraction:
            out.append((zone_id, float(min(frac, 1.0))))
    return out
