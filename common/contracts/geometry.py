"""Geometry primitives used across the vision and reconciliation layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def foot_point(self) -> tuple[float, float]:
        """Center-bottom -- used as the floor-projection anchor."""
        return ((self.x1 + self.x2) / 2.0, self.y2)


@dataclass(frozen=True)
class FloorPosition:
    """A point on the store floor, in meters."""

    x: float
    y: float
