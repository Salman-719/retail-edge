"""Shared doubles for cross-service pipeline tests (stub detector, fixed embedder,
tiny video generation, duck-typed calibration)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from common.contracts.detection import Detection
from common.contracts.geometry import BBox


class StubDetector:
    """Emits one slowly-moving person box per frame, ignoring frame content."""

    def __init__(self, start_x: float = 30.0, dx: float = 5.0, top: float = 50.0,
                 height: float = 150.0, width: float = 50.0, conf: float = 0.9):
        self._x = start_x
        self._dx, self._top, self._h, self._w, self._conf = dx, top, height, width, conf

    def detect(self, frame) -> list[Detection]:
        x = self._x
        self._x += self._dx
        return [Detection(bbox=BBox(x, self._top, x + self._w, self._top + self._h), confidence=self._conf)]


class FixedEmbedder:
    """Returns a fixed embedding regardless of crop -> deterministic ReID."""

    embedding_dim = 512

    def __init__(self, index: int):
        self._vec = np.zeros(self.embedding_dim, dtype=np.float32)
        self._vec[index] = 1.0

    def extract(self, crop) -> np.ndarray:
        return self._vec.copy()


def write_video(path: str, n_frames: int = 12, fps: float = 6.0,
                size: tuple[int, int] = (320, 240)) -> bool:
    import cv2

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    if not writer.isOpened():
        return False
    for _ in range(n_frames):
        writer.write(np.zeros((size[1], size[0], 3), dtype=np.uint8))
    writer.release()
    return True


def identity_calibration(cam_id: str):
    return SimpleNamespace(
        cam_id=cam_id,
        homography=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        zone_polygons={"zones": [{"zone_id": "floor", "polygon": [[0, 0], [320, 0], [320, 240], [0, 240]]}]},
    )
