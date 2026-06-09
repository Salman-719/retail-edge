"""Unit tests for camera→zone coverage geometry (pure, no DB).

Validates the footprint estimation and zone-overlap logic that feeds IEP3's
cross-camera overlap graph.
"""
import os
import sys

import pytest
from shapely.geometry import Polygon

# Make the EEP app importable (app.utils.camera_coverage) without pip install.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "services", "eep"),
)

from app.utils.camera_coverage import (  # noqa: E402
    CameraCalibration,
    camera_floor_footprint,
    frame_bounds_from_correspondences,
    zone_coverages,
)

import numpy as np  # noqa: E402

IDENTITY_H = np.eye(3, dtype=np.float64)  # camera px == floor-plan px


def _homography_calib(scale: float = 1.0) -> CameraCalibration:
    H = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]], dtype=np.float64)
    # ppm=1, origin=0 → world metres equal floor-plan pixels, so the homography
    # output maps 1:1 and the numeric assertions below stay simple.
    return CameraCalibration("homography", homography=H, ppm=1.0, origin_x=0.0, origin_y=0.0)


# ── project_pixel ─────────────────────────────────────────────────────────────

def test_homography_projects_identity():
    calib = _homography_calib()
    assert calib.project_pixel(10, 20) == (10.0, 20.0)


def test_homography_projects_scaled():
    calib = _homography_calib(scale=2.0)
    assert calib.project_pixel(10, 20) == (20.0, 40.0)


def test_homography_projects_to_world_metres_not_pixels():
    # Regression: project_pixel must return WORLD METRES (px - origin)/ppm, not
    # floor-plan pixels — otherwise the footprint never overlaps metre-space zones.
    H = np.eye(3, dtype=np.float64)  # frame px == map px
    calib = CameraCalibration("homography", homography=H, ppm=100.0, origin_x=0.0, origin_y=0.0)
    # map px (500, 300) → metres (5.0, 3.0)
    assert calib.project_pixel(500, 300) == (5.0, 3.0)


def test_homography_without_scale_returns_none():
    # No ppm/origin → cannot convert to metres → unusable.
    calib = CameraCalibration("homography", homography=np.eye(3))
    assert calib.project_pixel(10, 20) is None


def test_footprint_overlaps_metre_zone():
    # Full metre-space scenario: a camera footprint and a zone both in metres.
    H = np.eye(3, dtype=np.float64)
    calib = CameraCalibration("homography", homography=H, ppm=100.0, origin_x=0.0, origin_y=0.0)
    # 400x400 frame → metres footprint [0,4]x[0,4]
    fp = camera_floor_footprint(calib, 400, 400, grid=8)
    zone = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])  # metres, inside footprint
    cov = zone_coverages(fp, [("z", zone)])
    assert cov and cov[0][0] == "z" and cov[0][1] == pytest.approx(1.0)


def test_homography_degenerate_w_returns_none():
    # Last row makes w collapse to ~0 at this pixel.
    H = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 0]], dtype=np.float64)
    calib = CameraCalibration("homography", homography=H)
    assert calib.project_pixel(5, 5) is None


# ── footprint ─────────────────────────────────────────────────────────────────

def test_footprint_is_frame_square_under_identity():
    calib = _homography_calib()
    fp = camera_floor_footprint(calib, frame_width=100, frame_height=100, grid=8)
    assert fp is not None
    # Convex hull of a 100×100 grid is the 100×100 square.
    assert fp.area == pytest.approx(100 * 100, rel=1e-9)


def test_footprint_clipped_to_boundary():
    # 2× homography projects a 100×100 frame to 0..200, but the floor boundary
    # is only 0..100 — out-of-bounds samples are discarded.
    calib = _homography_calib(scale=2.0)
    boundary = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    fp = camera_floor_footprint(calib, 100, 100, boundary=boundary, grid=16)
    assert fp is not None
    # Footprint cannot exceed the boundary area.
    assert fp.area <= 100 * 100 + 1e-6
    assert fp.area > 0


def test_footprint_none_when_no_valid_points():
    boundary = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])  # tiny, far from FOV
    calib = _homography_calib(scale=1.0)
    # Frame projects to 0..1000 — only the (0,0) corner sample lands in boundary.
    fp = camera_floor_footprint(calib, 1000, 1000, boundary=boundary, grid=4)
    assert fp is None  # < 3 points survive


# ── zone_coverages ────────────────────────────────────────────────────────────

def test_zone_fully_covered():
    footprint = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    zone = Polygon([(0, 0), (50, 0), (50, 100), (0, 100)])  # left half, inside fp
    result = zone_coverages(footprint, [("zone-a", zone)])
    assert len(result) == 1
    assert result[0][0] == "zone-a"
    assert result[0][1] == pytest.approx(1.0)


def test_zone_partially_covered():
    footprint = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    zone = Polygon([(50, 0), (150, 0), (150, 100), (50, 100)])  # half outside fp
    result = zone_coverages(footprint, [("zone-c", zone)])
    assert len(result) == 1
    assert result[0][1] == pytest.approx(0.5, rel=1e-6)


def test_zone_not_covered_is_omitted():
    footprint = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    far_zone = Polygon([(200, 200), (300, 200), (300, 300), (200, 300)])
    result = zone_coverages(footprint, [("zone-far", far_zone)])
    assert result == []


def test_two_cameras_share_one_zone():
    """End-to-end: two footprints, shared middle zone → both cover it."""
    cam_a_fp = Polygon([(0, 0), (120, 0), (120, 100), (0, 100)])
    cam_b_fp = Polygon([(80, 0), (200, 0), (200, 100), (80, 100)])
    shared = Polygon([(90, 0), (110, 0), (110, 100), (90, 100)])
    only_a = Polygon([(0, 0), (20, 0), (20, 100), (0, 100)])

    cov_a = dict(zone_coverages(cam_a_fp, [("shared", shared), ("only_a", only_a)]))
    cov_b = dict(zone_coverages(cam_b_fp, [("shared", shared), ("only_a", only_a)]))

    assert "shared" in cov_a and "shared" in cov_b   # overlap edge exists
    assert "only_a" in cov_a and "only_a" not in cov_b


def test_frame_bounds_tps_format():
    corr = [
        {"frame_px": 100, "frame_py": 50, "world_x_m": 0, "world_y_m": 0},
        {"frame_px": 400, "frame_py": 50, "world_x_m": 1, "world_y_m": 0},
        {"frame_px": 250, "frame_py": 300, "world_x_m": 0.5, "world_y_m": 1},
    ]
    assert frame_bounds_from_correspondences(corr) == (100.0, 400.0, 50.0, 300.0)


def test_frame_bounds_homography_format():
    corr = [
        {"pixel": [10, 20], "world": [0, 0]},
        {"pixel": [90, 20], "world": [1, 0]},
        {"pixel": [50, 80], "world": [0.5, 1]},
    ]
    assert frame_bounds_from_correspondences(corr) == (10.0, 90.0, 20.0, 80.0)


def test_frame_bounds_insufficient_or_degenerate():
    assert frame_bounds_from_correspondences(None) is None
    assert frame_bounds_from_correspondences([{"pixel": [1, 2]}]) is None  # < 3
    # collinear in u → umax == umin
    assert frame_bounds_from_correspondences(
        [{"pixel": [5, 0]}, {"pixel": [5, 1]}, {"pixel": [5, 2]}]
    ) is None


def test_sample_region_bounds_the_footprint():
    # With ppm=1/origin=0, metres == frame px. Sampling only [100,300]x[100,300]
    # yields a footprint of exactly that region, ignoring frame_width/height.
    calib = CameraCalibration("homography", homography=np.eye(3), ppm=1.0, origin_x=0.0, origin_y=0.0)
    fp = camera_floor_footprint(calib, 9999, 9999, sample_region=(100, 300, 100, 300), grid=8)
    assert fp is not None
    assert fp.bounds == pytest.approx((100.0, 100.0, 300.0, 300.0))


def test_invalid_zone_polygon_is_repaired():
    footprint = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    # Bowtie (self-intersecting) polygon — buffer(0) repairs it.
    bowtie = Polygon([(10, 10), (50, 50), (10, 50), (50, 10)])
    result = zone_coverages(footprint, [("bowtie", bowtie)])
    # Should not raise; either covered or omitted, but well-defined.
    assert isinstance(result, list)
