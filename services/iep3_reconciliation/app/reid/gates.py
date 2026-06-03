"""Cross-camera spatial-temporal plausibility gate.
Pure function — no DB, no state, no imports beyond math.
Floor coordinates are in meters (coordinate_frame.units = 'meters').
"""
from __future__ import annotations

from math import hypot


def cross_camera_gate(
    new_x:         float,
    new_y:         float,
    new_ts:        int,      # epoch ms
    last_x:        float,
    last_y:        float,
    last_ts:       int,      # epoch ms
    max_speed_mps: float = 1.5,
) -> bool:
    """Return True if movement from (last_x, last_y, last_ts) to
    (new_x, new_y, new_ts) is physically plausible given max_speed_mps.

    If elapsed_s <= 0 (simultaneous or new observation predates the
    GlobalID's last update), the gate passes automatically — we cannot
    rule out the match on timing alone.

    Floor coordinates must be in the same unit as max_speed_mps (meters).
    """
    elapsed_s = (new_ts - last_ts) / 1000.0
    if elapsed_s <= 0:
        return True  # simultaneous — cannot exclude on timing
    distance_m = hypot(new_x - last_x, new_y - last_y)
    return (distance_m / elapsed_s) <= max_speed_mps
