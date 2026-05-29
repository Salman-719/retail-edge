"""Calibration loading + validation for IEP2 startup.

Two sources, one output shape ``(H_3x3, zones, bounds)``:

* ``load_calibration`` consumes the flat demo ``camera_calibrations`` row
  (``CameraCalibration`` ORM / the M6 seed tool).
* ``load_calibration_from_eep`` is the production adapter: it reads the existing
  EEP-owned ``calibrations.homography_matrix`` + ``zones.points`` tables and
  normalises them into the same shape.

The 9-element homography length is enforced here in application code (the DB
array column cannot enforce it).
"""

from __future__ import annotations

import numpy as np

from common.errors import CalibrationError


def _compute_store_bounds(zones: list[dict]) -> tuple[float, float, float, float]:
    """min/max over all zone polygon points. Falls back to an open plane when no
    zones are defined so projection bounds-checking never rejects everything."""
    xs: list[float] = []
    ys: list[float] = []
    for z in zones:
        for px, py in z["polygon"]:
            xs.append(float(px))
            ys.append(float(py))
    if not xs:
        return (-1e9, -1e9, 1e9, 1e9)
    return (min(xs), min(ys), max(xs), max(ys))


def _validate_homography(flat, cam_id: str) -> np.ndarray:
    if flat is None or len(flat) != 9:
        raise CalibrationError(
            f"homography for {cam_id} must have 9 elements, got "
            f"{0 if flat is None else len(flat)}"
        )
    return np.array(flat, dtype=np.float64).reshape(3, 3)


def load_calibration(row) -> tuple[np.ndarray, list[dict], tuple]:
    """row: a ``CameraCalibration`` ORM instance (demo/seed table)."""
    H = _validate_homography(row.homography, row.cam_id)
    zones = row.zone_polygons.get("zones", []) if row.zone_polygons else []
    return H, zones, _compute_store_bounds(zones)


def load_calibration_from_eep(
    homography_matrix, zone_rows: list[dict], cam_id: str
) -> tuple[np.ndarray, list[dict], tuple]:
    """Production adapter over EEP-owned tables.

    homography_matrix: the ``calibrations.homography_matrix`` JSONB (3x3 nested
        list or flat 9-list). zone_rows: rows from ``zones`` with ``id``/``name``
        and ``points`` (list of [x, y])."""
    flat = list(np.asarray(homography_matrix, dtype=np.float64).reshape(-1)) if homography_matrix else None
    H = _validate_homography(flat, cam_id)
    zones = [
        {"zone_id": str(z.get("id") or z.get("name")), "polygon": z["points"]}
        for z in zone_rows
        if z.get("points")
    ]
    return H, zones, _compute_store_bounds(zones)
