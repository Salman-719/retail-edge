"""Integration: one IEP2 runtime feeds a real DB, then one IEP3 batch reconciles
it -- the IEP2 -> IEP3 chain produces correct rows."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep2_vision.app.persistence.postgres import PostgresPersistence
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep2_vision.app.vision.reid import DescriptorEmbedder
from services.iep2_vision.app.vision.tracker import IouTracker
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository
from tests.pipeline.integration.helpers import StubDetector, identity_calibration, write_video

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("66666666-6666-6666-6666-666666666666")


class _FakeEmitter:
    def __init__(self):
        self.windows: list[tuple[int, int]] = []

    async def emit(self, store_id, camera_id, batch_number, window_start_ms, window_end_ms):
        self.windows.append((window_start_ms, window_end_ms))

    async def close(self):
        pass


async def _count(table: str) -> int:
    async with session_scope() as s:
        return (await s.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()


async def test_iep2_then_iep3_produces_rows(pg, tmp_path):
    video = str(tmp_path / "cam1.avi")
    if not write_video(video):
        pytest.skip("cv2.VideoWriter (MJPG) unavailable")

    settings = get_settings()
    emitter = _FakeEmitter()
    rt = Iep2Runtime(STORE, "cam1", settings)
    await rt.setup(
        identity_calibration("cam1"),
        detector=StubDetector(),
        tracker=IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5),
        embedder=DescriptorEmbedder(),
        persistence=PostgresPersistence(settings),
        events=emitter,
        warm_restart=False,
    )
    await rt.run(video, start_epoch_ms=0)

    assert await _count("tracking_history") > 0
    assert await _count("local_centroids") >= 1

    # Now reconcile the same window through IEP3.
    reconciler = Reconciler(STORE, Iep3Repository(settings), settings, frame_px={"cam1": 320 * 240})
    window = (0, 10_000)  # covers the whole short clip
    result = await reconciler.process_batch(0, window)

    assert result["new_locals"] >= 1
    assert await _count("global_identities") >= 1
    # exactly one canonical row per global per batch
    assert await _count("global_tracking_history") == await _count("global_identities")
