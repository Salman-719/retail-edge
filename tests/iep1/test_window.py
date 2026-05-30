"""WindowAccumulator gap detection + status classification."""

from __future__ import annotations

from common.config import get_settings
from services.iep1_ingestion.app.window import WindowAccumulator

# 60s window @ 5fps -> expected 300, sample interval 200ms, gap threshold 300ms.
WINDOW_MS = 60_000
FPS = 5.0


def _acc():
    return WindowAccumulator("cam1", "store", WINDOW_MS, FPS, get_settings())


def _fill(acc, start, count, step_ms=200):
    for i in range(count):
        ts = start + i * step_ms
        acc.add(ts, f"frames/cam1/{ts}.jpg")


def test_full_window_no_gaps_online():
    acc = _acc()
    _fill(acc, 0, 300)
    m = acc.close(0, WINDOW_MS, batch_number=0)
    assert m.captured_frames == 300
    assert m.camera_status == "online"
    assert m.gaps == []


def test_mid_window_hole_detected():
    acc = _acc()
    # frames 0..49 (0..9800ms), then a 15-slot hole, then resume
    _fill(acc, 0, 50)
    resume = 50 * 200 + 15 * 200  # skip 15 sample slots
    _fill(acc, resume, 50)
    m = acc.close(0, WINDOW_MS, batch_number=1)
    holes = [g for g in m.gaps if g.start_ms < resume <= g.end_ms]
    assert len(holes) == 1
    assert holes[0].missing_frames == 15


def test_trailing_gap_when_camera_dies_midwindow():
    acc = _acc()
    _fill(acc, 0, 50)  # ~10s of frames then nothing for the rest of the 60s window
    m = acc.close(0, WINDOW_MS, batch_number=2)
    assert m.gaps  # a trailing gap exists
    assert m.gaps[-1].end_ms == WINDOW_MS
    assert m.camera_status in ("degraded", "offline")


def test_status_classification_boundaries():
    s = get_settings()
    acc = _acc()
    # online boundary
    _fill(acc, 0, int(300 * s.online_frame_ratio))
    assert acc.close(0, WINDOW_MS, 0).camera_status == "online"
    # degraded band
    _fill(acc, 0, 150)
    assert acc.close(0, WINDOW_MS, 1).camera_status == "degraded"
    # offline (empty)
    assert acc.close(0, WINDOW_MS, 2).camera_status == "offline"


def test_offline_empty_window_is_well_formed():
    acc = _acc()
    m = acc.close(0, WINDOW_MS, batch_number=7)
    assert m.captured_frames == 0
    assert m.frame_keys == []
    assert m.camera_status == "offline"
    assert len(m.gaps) == 1 and m.gaps[0].start_ms == 0 and m.gaps[0].end_ms == WINDOW_MS
    assert m.batch_number == 7
    assert m.expected_frames == 300
