"""Tracker lifecycle tests (IoU backend -- no heavy deps required)."""

from __future__ import annotations

from common.contracts.detection import Detection
from common.contracts.geometry import BBox
from services.iep2_vision.app.vision.tracker import IouTracker, create_tracker


def _det(x: float, y: float, conf: float = 0.9) -> Detection:
    return Detection(bbox=BBox(x, y, x + 40, y + 100), confidence=conf)


def _make() -> IouTracker:
    return IouTracker(min_hits=2, max_age=2, track_thresh=0.3, match_thresh=0.3)


def test_factory_returns_iou_backend():
    t = create_tracker("iou", min_hits=2, max_age=2, track_thresh=0.3, match_thresh=0.3)
    assert isinstance(t, IouTracker)


def test_stable_id_and_new_then_confirmed():
    t = _make()
    # frame 1: appears, not yet confirmed (min_hits=2)
    out = t.update([_det(100, 100)], None)
    assert out.new == [] and out.confirmed == []
    # frame 2: second hit -> confirmed this frame => 'new'
    out = t.update([_det(102, 100)], None)
    assert len(out.new) == 1 and out.confirmed == []
    tid = out.new[0].track_id
    # frame 3: established => 'confirmed', same id
    out = t.update([_det(104, 100)], None)
    assert len(out.confirmed) == 1 and out.confirmed[0].track_id == tid
    assert out.new == []


def test_lost_after_max_age():
    t = _make()
    t.update([_det(100, 100)], None)
    out = t.update([_det(102, 100)], None)
    tid = out.new[0].track_id
    # disappears: misses 1, 2 (<= max_age, not yet lost), 3 (> max_age -> lost)
    assert t.update([], None).lost_track_ids == []
    assert t.update([], None).lost_track_ids == []
    assert t.update([], None).lost_track_ids == [tid]


def test_update_empty_advances_state():
    """Regression guard (M2 issue B2): update([]) must advance and emit lost."""
    t = _make()
    t.update([_det(100, 100)], None)
    out = t.update([_det(102, 100)], None)
    tid = out.new[0].track_id
    lost_seen = False
    for _ in range(5):
        if tid in t.update([], None).lost_track_ids:
            lost_seen = True
            break
    assert lost_seen


def test_unconfirmed_track_not_reported_lost():
    t = _make()
    t.update([_det(100, 100)], None)  # 1 hit, never confirmed
    for _ in range(5):
        assert t.update([], None).lost_track_ids == []
