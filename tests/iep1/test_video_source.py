"""VideoFileSource decimation + capture-time stamping (cv2 monkeypatched)."""

from __future__ import annotations

import numpy as np

import services.iep1_ingestion.app.source.video_source as vs_module
from services.iep1_ingestion.app.source.video_source import VideoFileSource


class _FakeCapture:
    """Yields n frames at src_fps (cv2.VideoCapture stand-in)."""

    def __init__(self, n_frames: int, src_fps: float):
        self._n = n_frames
        self._fps = src_fps
        self._i = 0

    def get(self, prop):
        return self._fps

    def read(self):
        if self._i >= self._n:
            return False, None
        frame = np.full((4, 4, 3), self._i % 255, dtype=np.uint8)
        self._i += 1
        return True, frame

    def isOpened(self):
        return True

    def release(self):
        pass


def test_decimation_to_target_fps(monkeypatch):
    monkeypatch.setattr(vs_module.cv2, "VideoCapture", lambda p: _FakeCapture(20, src_fps=10.0))
    src = VideoFileSource("x.mp4", target_fps=5.0, start_epoch_ms=1_000_000)
    out = list(src.frames())
    assert len(out) == 10  # 20 source frames @10fps -> 5fps
    ts = [t for t, _ in out]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)  # monotonic, unique
    assert ts[0] == 1_000_000
    assert ts[1] - ts[0] == 200  # 5 fps -> 200 ms spacing


def test_capture_ts_is_source_position_derived(monkeypatch):
    """capture_ts must be derived from the true SOURCE position (src_idx/src_fps),
    not the kept-frame count -- this is what preserves real elapsed time so gaps
    can't be collapsed. With src_fps=12, target=5, kept source indices are
    0,2,4,7,9,... (step 2.4); each ts must equal start + round(src_idx/12*1000)."""
    monkeypatch.setattr(vs_module.cv2, "VideoCapture", lambda p: _FakeCapture(24, src_fps=12.0))
    src = VideoFileSource("x.mp4", target_fps=5.0, start_epoch_ms=0)
    ts = [t for t, _ in src.frames()]

    # Reconstruct which source indices the decimator keeps (step = 12/5 = 2.4).
    step, next_keep, kept_src = 12.0 / 5.0, 0.0, []
    for src_idx in range(24):
        if src_idx >= next_keep:
            kept_src.append(src_idx)
            next_keep += step
    expected = [int((i / 12.0) * 1000) for i in kept_src]
    assert ts == expected
    # spacings are NOT uniform (2,2,3,2,... source frames apart) -> proves it is
    # source-position-derived, not a fixed kept-index*200ms clock.
    spacings = {b - a for a, b in zip(ts, ts[1:])}
    assert len(spacings) > 1
