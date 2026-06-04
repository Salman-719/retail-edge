"""Cross-camera spatial-temporal plausibility gate.
Pure function — no DB, no state.
Floor coordinates are in meters (coordinate_frame.units = 'meters').
"""
from __future__ import annotations

import logging
from math import hypot

logger = logging.getLogger(__name__)


def cross_camera_gate(
    new_x:         float | None,
    new_y:         float | None,
    new_ts:        int,
    last_x:        float | None,
    last_y:        float | None,
    last_ts:       int,
    max_speed_mps: float = 1.5,
) -> bool:
    """Return True if movement from (last_x, last_y, last_ts) to
    (new_x, new_y, new_ts) is physically plausible given max_speed_mps.

    NULL coordinates: uncalibrated camera — no spatial data available.
    Policy: pass gate, rely on appearance similarity only.

    Negative elapsed_s: clock skew between cameras. Pass gate and warn.
    elapsed_s == 0: simultaneous observation — pass gate.
    """
    if new_x is None or new_y is None or last_x is None or last_y is None:
        # Uncalibrated camera — no spatial data available.
        # Policy: pass gate, rely on appearance similarity only.
        return True

    elapsed_s = (new_ts - last_ts) / 1000.0

    if elapsed_s < 0:
        logger.warning(
            "Negative elapsed_s=%.3f in cross_camera_gate "
            "(new_ts=%d last_ts=%d) — possible clock skew",
            elapsed_s, new_ts, last_ts,
        )
        return True

    if elapsed_s == 0:
        return True

    distance_m = hypot(new_x - last_x, new_y - last_y)
    max_dist_m = max_speed_mps * elapsed_s
    return distance_m <= max_dist_m
