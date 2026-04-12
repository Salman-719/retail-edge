"""Unit tests for EEP Pydantic schemas and homography utilities."""
import sys
import os

# Allow importing from the eep service without installing it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/eep"))

import pytest
from pydantic import ValidationError


# ─── StoreCreate ─────────────────────────────────────────────────────────────

class TestStoreCreate:
    def test_valid(self):
        from app.models.schemas import StoreCreate
        s = StoreCreate(name="Test Store")
        assert s.name == "Test Store"

    def test_missing_name(self):
        from app.models.schemas import StoreCreate
        with pytest.raises(ValidationError):
            StoreCreate()


# ─── ZoneCreate ──────────────────────────────────────────────────────────────

class TestZoneCreate:
    def _points(self):
        return [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}]

    def test_valid_types(self):
        from app.models.schemas import ZoneCreate
        for t in ("entrance", "checkout", "aisle", "staff_only", "general"):
            z = ZoneCreate(name="Z", type=t, points=self._points())
            assert z.type == t

    def test_invalid_type(self):
        from app.models.schemas import ZoneCreate
        with pytest.raises(ValidationError):
            ZoneCreate(name="Z", type="unknown_type", points=self._points())

    def test_optional_id(self):
        from app.models.schemas import ZoneCreate
        z = ZoneCreate(name="Z", type="general", points=self._points())
        assert z.id is None

        z2 = ZoneCreate(id="abc123", name="Z", type="general", points=self._points())
        assert z2.id == "abc123"

    def test_min_points_not_enforced_by_schema(self):
        from app.models.schemas import ZoneCreate
        # Schema doesn't enforce min points — that's a business rule
        z = ZoneCreate(name="Z", type="general", points=[{"x": 0, "y": 0}])
        assert len(z.points) == 1


# ─── CameraCreate ─────────────────────────────────────────────────────────────

class TestCameraCreate:
    def test_minimal(self):
        from app.models.schemas import CameraCreate
        c = CameraCreate(name="Cam A")
        assert c.name == "Cam A"
        assert c.position_x is None

    def test_full(self):
        from app.models.schemas import CameraCreate
        c = CameraCreate(name="Cam A", position_x=1.5, position_y=2.0, height_meters=3.0)
        assert c.position_x == 1.5
        assert c.height_meters == 3.0


# ─── CalibrationRequest ───────────────────────────────────────────────────────

class TestCalibrationRequest:
    def _corr(self, n=4):
        return [
            {"camPx": {"x": float(i * 10), "y": float(i * 10)},
             "floorM": {"x": float(i), "y": float(i)}}
            for i in range(n)
        ]

    def test_valid(self):
        from app.models.schemas import CalibrationRequest
        req = CalibrationRequest(correspondences=self._corr())
        assert len(req.correspondences) == 4

    def test_empty_correspondences(self):
        from app.models.schemas import CalibrationRequest
        req = CalibrationRequest(correspondences=[])
        assert len(req.correspondences) == 0


# ─── homography utility ───────────────────────────────────────────────────────

class TestComputeHomography:
    def _correspondences(self):
        return [
            {"camPx": {"x": 0.0, "y": 0.0}, "floorM": {"x": 0.0, "y": 0.0}},
            {"camPx": {"x": 100.0, "y": 0.0}, "floorM": {"x": 5.0, "y": 0.0}},
            {"camPx": {"x": 100.0, "y": 100.0}, "floorM": {"x": 5.0, "y": 5.0}},
            {"camPx": {"x": 0.0, "y": 100.0}, "floorM": {"x": 0.0, "y": 5.0}},
        ]

    def test_requires_four_points(self):
        from app.utils.homography import compute_homography
        result = compute_homography(self._correspondences()[:3])
        assert result["status"] == "failed"
        assert "Minimum 4" in result["error"]

    def test_valid_returns_matrix(self):
        from app.utils.homography import compute_homography
        result = compute_homography(self._correspondences())
        assert result["status"] in ("ok", "rejected")
        assert result["homography_matrix"] is not None
        assert len(result["homography_matrix"]) == 3

    def test_mean_error_present(self):
        from app.utils.homography import compute_homography
        result = compute_homography(self._correspondences())
        assert "mean_error" in result
        assert isinstance(result["mean_error"], float)

    def test_collinear_points(self):
        from app.utils.homography import compute_homography
        # All points on y=0 line — degenerate
        corr = [
            {"camPx": {"x": float(i * 10), "y": 0.0}, "floorM": {"x": float(i), "y": 0.0}}
            for i in range(4)
        ]
        result = compute_homography(corr)
        # Should either fail or have high reprojection error
        assert result["status"] in ("failed", "rejected")


# ─── ScaleConfig ─────────────────────────────────────────────────────────────

class TestScaleConfig:
    def test_valid(self):
        from app.models.schemas import ScaleConfig
        sc = ScaleConfig(
            origin_x=100.0, origin_y=200.0,
            scale_point1_x=100.0, scale_point1_y=200.0,
            scale_point2_x=200.0, scale_point2_y=200.0,
            real_world_distance_m=5.0,
            pixels_per_meter=20.0,
        )
        assert sc.pixels_per_meter == 20.0

    def test_optional_fields(self):
        from app.models.schemas import ScaleConfig
        sc = ScaleConfig(pixels_per_meter=50.0)
        assert sc.origin_x is None
