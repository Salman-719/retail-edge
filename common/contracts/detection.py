"""Detection contracts produced by the M2 vision layer."""

from __future__ import annotations

from dataclasses import dataclass

from common.contracts.geometry import BBox


@dataclass
class Detection:
    """Raw detector output for one person in one frame."""

    bbox: BBox
    confidence: float


@dataclass
class TrackedDetection:
    """A detection that the tracker has associated to a track."""

    track_id: int
    bbox: BBox
    confidence: float
