"""Spatial-temporal plausibility gate (walking-speed filter)."""

from __future__ import annotations

from math import hypot


def spatial_temporal_gate(
    new_x: float,
    new_y: float,
    new_ts: int,
    last_x: float,
    last_y: float,
    last_ts: int,
    max_speed_mps: float,
) -> bool:
    """True if a person could plausibly have moved between the two points.

    ``elapsed_s <= 0`` (same/earlier timestamp) accepts, with no division by zero
    (M3 review issue B1)."""
    distance = hypot(new_x - last_x, new_y - last_y)
    elapsed_s = (new_ts - last_ts) / 1000.0
    if elapsed_s <= 0:
        return True
    return (distance / elapsed_s) <= max_speed_mps
