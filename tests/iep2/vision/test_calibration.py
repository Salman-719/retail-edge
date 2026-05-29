"""Calibration loader + EEP adapter tests."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from common.errors import CalibrationError
from services.iep2_vision.app.calibration import load_calibration, load_calibration_from_eep


@dataclass
class _Row:
    cam_id: str
    homography: list
    zone_polygons: dict


def test_nine_element_homography_loads():
    row = _Row(
        cam_id="cam1",
        homography=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        zone_polygons={"zones": [{"zone_id": "A", "polygon": [[0, 0], [10, 0], [10, 10]]}]},
    )
    H, zones, bounds = load_calibration(row)
    assert H.shape == (3, 3)
    assert zones[0]["zone_id"] == "A"
    assert bounds == (0.0, 0.0, 10.0, 10.0)


def test_eight_element_homography_raises():
    row = _Row(cam_id="cam1", homography=[1, 0, 0, 0, 1, 0, 0, 0], zone_polygons={})
    with pytest.raises(CalibrationError):
        load_calibration(row)


def test_none_homography_raises():
    row = _Row(cam_id="cam1", homography=None, zone_polygons={})
    with pytest.raises(CalibrationError):
        load_calibration(row)


def test_eep_adapter_normalizes_nested_matrix_and_zones():
    H, zones, bounds = load_calibration_from_eep(
        homography_matrix=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        zone_rows=[{"id": "z1", "name": "Aisle", "points": [[0, 0], [5, 0], [5, 5]]}],
        cam_id="cam2",
    )
    assert np.allclose(H, np.eye(3))
    assert zones[0]["zone_id"] == "z1"
    assert zones[0]["polygon"] == [[0, 0], [5, 0], [5, 5]]
    assert bounds == (0.0, 0.0, 5.0, 5.0)
