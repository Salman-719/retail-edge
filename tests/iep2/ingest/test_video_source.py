"""VideoFrameSource sampling math (cv2.VideoCapture monkeypatched)."""

from __future__ import annotations

import numpy as np

import services.iep2_vision.app.ingest.video_source as vs_module
from services.iep2_vision.app.ingest.video_source import VideoFrameSource


class _FakeCapture:
    def __init__(self, n_frames: int, src_fps: float):
        self._n = n_frames
        self._fps = src_fps
        self._i = 0

    def get(self, prop):
        return self._fps  # CAP_PROP_FPS

    def read(self):
        if self._i >= self._n:
            return False, None
        frame = np.full((4, 4, 3), self._i, dtype=np.uint8)
        self._i += 1
        return True, frame

    def release(self):
        pass


def test_samples_at_target_fps_with_monotonic_timestamps(monkeypatch):
    monkeypatch.setattr(vs_module.cv2, "VideoCapture", lambda path: _FakeCapture(10, src_fps=10.0))

    source = VideoFrameSource("ignored.mp4", target_fps=5.0, start_epoch_ms=1_000_000)
    samples = list(source)

    assert len(samples) == 5  # 10 src frames at 10fps sampled to 5fps
    assert [s.frame_index for s in samples] == [0, 1, 2, 3, 4]
    assert [s.timestamp_ms - 1_000_000 for s in samples] == [0, 200, 400, 600, 800]
    # timestamps strictly increasing
    ts = [s.timestamp_ms for s in samples]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_target_fps_capped_at_source(monkeypatch):
    monkeypatch.setattr(vs_module.cv2, "VideoCapture", lambda path: _FakeCapture(4, src_fps=3.0))
    # request 30fps but source is 3fps -> every source frame sampled
    samples = list(VideoFrameSource("x.mp4", target_fps=30.0, start_epoch_ms=0))
    assert len(samples) == 4
