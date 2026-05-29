"""End-to-end IEP2 runtime against a real DB and a generated video.

Uses a stub detector + IoU tracker + descriptor embedder (no weights/GPU) so the
full chain video -> pipeline -> identity -> persistence -> batch_complete runs in
CI. Asserts rows land in all three IEP2 tables and a batch_complete is emitted.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from common.config import get_settings
from common.contracts.detection import Detection
from common.contracts.geometry import BBox
from common.db.engine import session_scope
from services.iep2_vision.app.persistence.postgres import PostgresPersistence
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep2_vision.app.vision.reid import DescriptorEmbedder
from services.iep2_vision.app.vision.tracker import IouTracker

pytestmark = pytest.mark.asyncio


class _StubDetector:
    """Emits one slowly-moving person box per frame, ignoring frame content."""

    def __init__(self):
        self._x = 30.0

    def detect(self, frame) -> list[Detection]:
        self._x += 5.0
        return [Detection(bbox=BBox(self._x, 50, self._x + 50, 200), confidence=0.9)]


class _FakeEmitter:
    def __init__(self):
        self.emitted: list[tuple] = []

    async def emit(self, store_id, camera_id, batch_number, window_start_ms, window_end_ms):
        self.emitted.append((store_id, camera_id, batch_number, window_start_ms, window_end_ms))

    async def close(self):
        pass


def _write_video(path: str, n_frames: int = 20, fps: float = 10.0) -> bool:
    import cv2

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    if not writer.isOpened():
        return False
    for _ in range(n_frames):
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    writer.release()
    return True


async def _count(table: str) -> int:
    from sqlalchemy import text

    async with session_scope() as s:
        return (await s.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()


async def test_full_runtime_populates_tables_and_emits_batch(pg, tmp_path):
    video = str(tmp_path / "cam1.avi")
    if not _write_video(video):
        pytest.skip("cv2.VideoWriter (MJPG) unavailable in this environment")

    settings = get_settings()
    cal = SimpleNamespace(
        cam_id="cam1",
        homography=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        zone_polygons={"zones": [{"zone_id": "A", "polygon": [[0, 0], [320, 0], [320, 240], [0, 240]]}]},
    )
    emitter = _FakeEmitter()
    runtime = Iep2Runtime("store-demo", "cam1", settings)
    await runtime.setup(
        cal,
        detector=_StubDetector(),
        tracker=IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5),
        embedder=DescriptorEmbedder(),
        persistence=PostgresPersistence(settings),
        events=emitter,
    )
    await runtime.run(video, start_epoch_ms=1_000_000)

    assert await _count("tracking_history") > 0
    assert await _count("local_embeddings") >= 1
    assert await _count("local_centroids") == 1  # one Local ID
    assert len(emitter.emitted) >= 1
    assert emitter.emitted[0][1] == "cam1"
