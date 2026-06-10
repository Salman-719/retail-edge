"""VideoFileSource — feeds frames from a video file through the FrameSource protocol.

Timestamps are synthetic: start_epoch_ms anchors frame 0 to a real wall-clock
epoch so S3 keys and IEP2 consumer-group ordering are valid.
"""
import logging
import time
from typing import Iterator, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VideoFileSource:
    def __init__(self, video_path: str, target_fps: float, start_epoch_ms: int) -> None:
        self._video_path     = video_path
        self._target_fps     = target_fps
        self._start_epoch_ms = start_epoch_ms
        self._available      = False
        self._cap: cv2.VideoCapture | None = None

    def frames(self) -> Iterator[Tuple[int, np.ndarray]]:
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            logger.error("Cannot open video file: %s", self._video_path)
            cap.release()
            return

        source_fps = cap.get(cv2.CAP_PROP_FPS)
        if not source_fps or source_fps <= 0:
            logger.warning("Could not read source FPS from %s, defaulting to target_fps=%.1f", self._video_path, self._target_fps)
            source_fps = self._target_fps

        # Cap target_fps to actual source FPS — no upsampling
        effective_fps = min(self._target_fps, source_fps)
        n = max(1, round(source_fps / effective_fps))

        logger.info(
            "VideoFileSource  path=%s  source_fps=%.2f  target_fps=%.2f  decimation_n=%d",
            self._video_path, source_fps, effective_fps, n,
        )

        self._cap = cap
        self._available = True
        frame_index = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_index % n == 0:
                    capture_ts_ms = self._start_epoch_ms + int(frame_index * 1000 / source_fps)
                    yield capture_ts_ms, frame

                frame_index += 1
        finally:
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._available = False
