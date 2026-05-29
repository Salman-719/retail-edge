"""FloorProjector tests with a known homography."""

from __future__ import annotations

import numpy as np

from common.contracts.geometry import BBox, FloorPosition
from services.iep2_vision.app.vision.projection import FloorProjector


# Identity homography maps pixel foot-point -> floor coords 1:1.
IDENTITY = np.eye(3)
ZONES = [{"zone_id": "A", "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]]}]
BOUNDS = (0.0, 0.0, 100.0, 100.0)


def test_projects_foot_point_within_bounds():
    proj = FloorProjector(IDENTITY, ZONES, BOUNDS)
    # foot point of this bbox = ((10+30)/2, 40) = (20, 40), inside bounds
    pos = proj.project(BBox(10, 0, 30, 40))
    assert pos is not None
    assert pos.x == 20.0 and pos.y == 40.0


def test_outside_bounds_returns_none():
    proj = FloorProjector(IDENTITY, ZONES, BOUNDS)
    pos = proj.project(BBox(200, 200, 240, 300))  # foot point (220, 300) outside
    assert pos is None


def test_degenerate_projection_returns_none():
    # Homography whose last row zeroes out the homogeneous w -> behind camera.
    H = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 0]], dtype=np.float64)
    proj = FloorProjector(H, ZONES, BOUNDS)
    assert proj.project(BBox(10, 0, 30, 40)) is None


def test_zone_assignment():
    proj = FloorProjector(IDENTITY, ZONES, BOUNDS)
    assert proj.zone_of(FloorPosition(10, 10)) == "A"
    assert proj.zone_of(FloorPosition(80, 80)) is None
