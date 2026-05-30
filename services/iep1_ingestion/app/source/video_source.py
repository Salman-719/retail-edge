"""Video-file frame source (current mode).

Decimates a video to ``target_fps``, stamping each kept frame with a
**capture timestamp** derived from its true position in the source timeline
(``start + src_idx/src_fps``). This preserves real elapsed time so that dropped/
skipped source frames become genuine gaps downstream (not collapsed by an
index-derived clock). End-of-file is a clean stop.
"""

from __future__ import annotations

from collections.abc import Iterator

import cv2
import numpy as np


class VideoFileSource:
    def __init__(self, video_path: str, target_fps: float, start_epoch_ms: int):
        self._cap = cv2.VideoCapture(video_path)
        self._src_fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._target = min(target_fps, self._src_fps)
        self._start = start_epoch_ms

    def frames(self) -> Iterator[tuple[int, np.ndarray]]:
        step = self._src_fps / self._target  # source frames per kept frame
        next_keep, src_idx = 0.0, 0
        while True:
            ok, frame = self._cap.read()
            if not ok:
                break  # EOF: clean stop
            if src_idx >= next_keep:
                capture_ts = self._start + int((src_idx / self._src_fps) * 1000)
                yield capture_ts, frame
                next_keep += step
            src_idx += 1
        self._cap.release()

    def is_available(self) -> bool:
        return self._cap.isOpened()
