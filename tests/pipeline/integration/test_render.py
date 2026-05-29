"""Smoke test for the annotated-video renderer: after a populated run it draws
Global IDs onto a re-read video and writes a non-empty output file."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from common.config import get_settings
from services.iep2_vision.app.persistence.postgres import PostgresPersistence
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep2_vision.app.vision.reid import DescriptorEmbedder
from services.iep2_vision.app.vision.tracker import IouTracker
from services.iep3_reconciliation.app.reconciler import Reconciler
from services.iep3_reconciliation.app.repository import Iep3Repository
from tools.demo.render import render_camera
from tools.seed_calibration import seed_calibration
from tests.pipeline.integration.helpers import StubDetector, identity_calibration, write_video

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("88888888-8888-8888-8888-888888888888")


class _NullEmitter:
    async def emit(self, *a):
        pass

    async def close(self):
        pass


async def test_render_writes_annotated_video(pg, tmp_path):
    video = str(tmp_path / "cam1.avi")
    if not write_video(video):
        pytest.skip("cv2.VideoWriter (MJPG) unavailable")

    settings = get_settings()
    await seed_calibration(STORE, ["cam1"])  # render reads homography from camera_calibrations

    rt = Iep2Runtime(STORE, "cam1", settings)
    await rt.setup(identity_calibration("cam1"), detector=StubDetector(),
                   tracker=IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5),
                   embedder=DescriptorEmbedder(), persistence=PostgresPersistence(settings),
                   events=_NullEmitter(), warm_restart=False)
    await rt.run(video, start_epoch_ms=0)

    reconciler = Reconciler(STORE, Iep3Repository(settings), settings, frame_px={"cam1": 320 * 240})
    await reconciler.process_batch(0, (0, 10_000))

    out = await render_camera(video, "cam1", str(tmp_path / "annotated_cam1.mp4"),
                              start_ms=0, sample_fps=settings.sample_rate_fps)
    assert Path(out).exists() and Path(out).stat().st_size > 0
