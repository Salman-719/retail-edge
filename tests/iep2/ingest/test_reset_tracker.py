"""VisionPipeline.reset_tracker: rebuilds from the factory; no-ops without one."""

from __future__ import annotations

from common.config import get_settings
from services.iep2_vision.app.vision.pipeline import VisionPipeline
from services.iep2_vision.app.vision.tracker import IouTracker


def _tracker():
    return IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5)


def test_reset_rebuilds_from_factory():
    built = []

    def factory():
        t = _tracker()
        built.append(t)
        return t

    first = factory()
    pipe = VisionPipeline(detector=None, tracker=first, projector=None,
                          settings=get_settings(), tracker_factory=factory)
    assert pipe.reset_tracker() is True
    assert pipe._tracker is not first  # a fresh instance replaced the old one
    assert len(built) == 2


def test_reset_is_noop_without_factory():
    injected = _tracker()
    pipe = VisionPipeline(detector=None, tracker=injected, projector=None, settings=get_settings())
    assert pipe.reset_tracker() is False
    assert pipe._tracker is injected  # unchanged
