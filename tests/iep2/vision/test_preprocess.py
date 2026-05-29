"""Duplicate suppression + low-quality filter tests."""

from __future__ import annotations

from common.contracts.detection import TrackedDetection
from common.contracts.geometry import BBox
from services.iep2_vision.app.vision.preprocess import filter_low_quality, suppress_duplicates


def _td(track_id: int, box: tuple[float, float, float, float]) -> TrackedDetection:
    return TrackedDetection(track_id=track_id, bbox=BBox(*box), confidence=0.9)


def test_overlapping_boxes_collapse_to_one():
    a = _td(1, (0, 0, 40, 100))
    b = _td(2, (2, 2, 42, 102))  # heavy overlap with a
    kept, suppressed = suppress_duplicates([a, b], iou_thresh=0.65, containment_thresh=0.78)
    assert suppressed == 1
    assert [d.track_id for d in kept] == [1]


def test_non_overlapping_boxes_kept():
    a = _td(1, (0, 0, 40, 100))
    b = _td(2, (200, 0, 240, 100))
    kept, suppressed = suppress_duplicates([a, b], iou_thresh=0.65, containment_thresh=0.78)
    assert suppressed == 0
    assert len(kept) == 2


def test_undersized_box_filtered():
    frame_shape = (480, 640)
    small = _td(1, (0, 0, 10, 20))  # height 20 / 480 < 0.12
    good = _td(2, (0, 0, 40, 120))  # height 120 / 480 = 0.25, aspect 3.0
    kept, filtered = filter_low_quality(
        [small, good], frame_shape, min_height_ratio=0.12, min_aspect_ratio=1.15
    )
    assert filtered == 1
    assert [d.track_id for d in kept] == [2]


def test_wrong_aspect_filtered():
    frame_shape = (480, 640)
    wide = _td(1, (0, 0, 200, 120))  # aspect 120/200 = 0.6 < 1.15
    kept, filtered = filter_low_quality(
        [wide], frame_shape, min_height_ratio=0.12, min_aspect_ratio=1.15
    )
    assert filtered == 1 and kept == []
