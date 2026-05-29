"""Floor projection & zone assignment (pure geometry).

Converts a pixel bbox to a store-floor position via homography and assigns a
zone. Homography and zone polygons are loaded once at startup (the DB read lives
in calibration.py); this module just consumes them.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Point, Polygon

from common.contracts.geometry import BBox, FloorPosition


class FloorProjector:
    def __init__(
        self,
        homography_3x3: np.ndarray,
        zone_polygons: list[dict],
        store_bounds: tuple[float, float, float, float],
    ):
        self._H = np.asarray(homography_3x3, dtype=np.float64).reshape(3, 3)
        self._zones = [(z["zone_id"], Polygon(z["polygon"])) for z in zone_polygons]
        self._min_x, self._min_y, self._max_x, self._max_y = store_bounds

    def project(self, bbox: BBox) -> FloorPosition | None:
        """Project the foot point to floor coords. Returns None if behind the
        camera or outside store bounds."""
        cx, cy = bbox.foot_point
        p = self._H @ np.array([cx, cy, 1.0])
        if abs(p[2]) < 1e-9:
            return None  # degenerate / behind camera
        x, y = p[0] / p[2], p[1] / p[2]
        if not (self._min_x <= x <= self._max_x and self._min_y <= y <= self._max_y):
            return None
        return FloorPosition(x=float(x), y=float(y))

    def zone_of(self, pos: FloorPosition) -> str | None:
        pt = Point(pos.x, pos.y)
        for zone_id, poly in self._zones:
            if pt.within(poly):
                return zone_id
        return None
