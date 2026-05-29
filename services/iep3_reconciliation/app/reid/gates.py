"""Cross-camera spatial-temporal gate -- the same plausibility filter as IEP2,
applied across cameras on the shared floor coordinate system."""

from __future__ import annotations

from math import hypot


def cross_camera_gate(
    new_x: float, new_y: float, new_ts: int, last_x: float, last_y: float, last_ts: int,
    max_speed_mps: float,
) -> bool:
    elapsed_s = (new_ts - last_ts) / 1000.0
    if elapsed_s <= 0:
        return True
    return (hypot(new_x - last_x, new_y - last_y) / elapsed_s) <= max_speed_mps
