"""Video frame source.

IEP2 reads a video file directly and samples it at the configured FPS. Each
sampled frame gets a synthetic epoch-ms timestamp derived from its position in
the video, so downstream identity logic sees the same time domain as a live
feed. This module is the ONLY place that changes if IEP1 streaming is
reintroduced -- swapping it for a ``RedisStreamFrameSource`` leaves M2/M3
untouched; the seam is ``SampledFrame``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SampledFrame:
    frame: np.ndarray  # BGR
    timestamp_ms: int  # synthetic: start_epoch_ms + offset within video
    frame_index: int  # index in the sampled timeline


class VideoFrameSource:
    """Samples a video at ``target_fps``, mapping each sample to an epoch-ms
    timestamp starting at ``start_epoch_ms``."""

    def __init__(self, video_path: str, target_fps: float, start_epoch_ms: int):
        self._cap = cv2.VideoCapture(video_path)
        self._src_fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._target_fps = min(target_fps, self._src_fps)
        self._start = start_epoch_ms

    def __iter__(self):
        idx = 0
        step = self._src_fps / self._target_fps  # source frames per sampled frame
        next_src = 0.0
        src_idx = 0
        while True:
            ok, frame = self._cap.read()
            if not ok:
                break
            if src_idx >= next_src:
                ts = self._start + int((idx / self._target_fps) * 1000)
                yield SampledFrame(frame=frame, timestamp_ms=ts, frame_index=idx)
                idx += 1
                next_src += step
            src_idx += 1
        self._cap.release()
