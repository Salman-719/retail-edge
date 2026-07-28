"""IEP1 WindowAccumulator unit tests.

The window accumulator is pure logic (dedup, gap detection, batch trigger,
online/degraded/offline status). window.py imports only stdlib, so we load it by
file path — collision-free and no infra. (IEP1's first unit tests.)
"""
import importlib.util
from pathlib import Path

import pytest

_WINDOW = (
    Path(__file__).resolve().parents[3]
    / "services" / "iep1_ingestion" / "app" / "window.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("iep1_window_under_test", _WINDOW)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


win = _load()
BASE = 1_000_000_000_000  # arbitrary epoch-ms base


def _acc(fps=5.0, window_s=10.0, batch_frames=None):
    # fps=5 -> 200ms interval, expected = round(10*5) = 50 frames.
    return win.WindowAccumulator(sample_fps=fps, batch_window_seconds=window_s, batch_frames=batch_frames)


def test_dedup_rejects_frames_closer_than_interval():
    acc = _acc()
    acc.add(BASE, "f0.jpg")
    acc.add(BASE + 50, "f1.jpg")  # 50ms << 0.9*200ms -> rejected
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.frame_count == 1


def test_accepts_frame_at_interval():
    acc = _acc()
    acc.add(BASE, "f0.jpg")
    acc.add(BASE + 200, "f1.jpg")
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.frame_count == 2


def test_gap_recorded_on_large_gap():
    acc = _acc()
    acc.add(BASE, "f0.jpg")
    acc.add(BASE + 400, "f1.jpg")  # 400ms > 1.5*200ms -> gap
    m = acc.close(BASE, BASE + 10_000, 1)
    assert len(m.gaps) == 1
    assert m.gaps[0].duration_ms == 400


def test_no_gap_on_regular_cadence():
    acc = _acc()
    for i in range(10):
        acc.add(BASE + i * 200, f"f{i}.jpg")
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.gaps == []
    assert m.frame_count == 10


@pytest.mark.parametrize(
    "n_frames,expected_status",
    [(50, "online"), (45, "online"), (25, "degraded"), (15, "degraded"), (10, "offline"), (5, "offline"), (0, "offline")],
)
def test_status_from_frame_ratio(n_frames, expected_status):
    acc = _acc()  # expected_frames = 50
    for i in range(n_frames):
        acc.add(BASE + i * 200, f"f{i}.jpg")
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.frame_count == n_frames
    assert m.status == expected_status


def test_batch_frames_never_signals_a_flush():
    """batch_frames is a SIZING hint, not a boundary.

    It used to return True at the Nth frame, and the caller then set
    window_start to that frame's timestamp. Each window therefore lasted
    frames/actual_fps instead of window_seconds, so every camera drifted off the
    shared wall-clock grid at its own rate (measured: 43 ms per window between
    two cameras) until pairs of cameras landed in different IEP3 buckets and
    cross-camera identity merging silently stopped. Boundaries are now the
    caller's, taken from the clock — see ADR-003.
    """
    acc = _acc(batch_frames=3)
    for i in range(5):
        assert acc.add(BASE + i * 200, f"f{i}.jpg") is None
    assert acc.close(BASE, BASE + 10_000, 1).frame_count == 5


def test_batch_frames_sets_expected_frames():
    acc = _acc(batch_frames=3)
    for i in range(3):
        acc.add(BASE + i * 200, f"f{i}.jpg")
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.expected_frames == 3
    assert m.status == "online"          # 3/3


def test_short_window_prorates_expected_frames():
    """A window covering a fraction of the nominal span expects that fraction.

    Without proration the first window after a camera starts mid-grid can never
    reach the 80% online threshold, so it is published "offline" — and IEP2
    skips offline windows outright, silently discarding real footage.
    """
    acc = _acc()                          # nominal 10s @5fps -> 50 frames
    for i in range(10):                   # 2s of frames at cadence
        acc.add(BASE + i * 200, f"f{i}.jpg")
    m = acc.close(BASE, BASE + 2_000, 1)  # 2s window -> expect 10
    assert m.expected_frames == 10
    assert m.status == "online"


def test_full_window_is_not_prorated():
    acc = _acc()
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.expected_frames == 50


def test_oversized_span_does_not_inflate_expected():
    acc = _acc()
    m = acc.close(BASE, BASE + 30_000, 1)
    assert m.expected_frames == 50


def test_reset_clears_frames_and_gaps():
    acc = _acc()
    acc.add(BASE, "f0.jpg")
    acc.add(BASE + 400, "f1.jpg")
    acc.reset()
    m = acc.close(BASE, BASE + 10_000, 1)
    assert m.frame_count == 0 and m.gaps == []
