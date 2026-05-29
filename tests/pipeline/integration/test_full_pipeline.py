"""End-to-end (IEP3 spec / M6 §8.2): the 3-camera scenario through the full
orchestrated IEP2 -> IEP3 chain. Cam1 sees one person (zone A); Cam2 + Cam3 see
the SAME person (zone B, two angles). Assert the Cam2/Cam3 person resolves to ONE
Global ID, Cam1 to a separate one, with one canonical position per Global ID."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep2_vision.app.vision.tracker import IouTracker
from tools.orchestrator import RunPlan, run
from tests.pipeline.integration.helpers import (
    FixedEmbedder,
    StubDetector,
    identity_calibration,
    write_video,
)

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("77777777-7777-7777-7777-777777777777")


def _tracker():
    return IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5)


async def test_three_camera_pipeline_one_global_across_cam2_cam3(pg, tmp_path):
    videos = {}
    for cam in ("cam1", "cam2", "cam3"):
        path = str(tmp_path / f"{cam}.avi")
        if not write_video(path):
            pytest.skip("cv2.VideoWriter (MJPG) unavailable")
        videos[cam] = path

    # cam1 distinct appearance; cam2 + cam3 share an appearance (same person).
    overrides = {
        "cam1": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(1)),
        "cam2": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(7)),
        "cam3": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(7)),
    }
    calibrations = {cam: identity_calibration(cam) for cam in videos}
    frame_px = {cam: 320 * 240 for cam in videos}

    await run(RunPlan(STORE, videos, frame_px), calibrations, overrides=overrides,
              settings=get_settings(), start_ms=0)

    async def cam_global(cam):
        async with session_scope() as s:
            return (await s.execute(text(
                "SELECT global_id FROM global_local_mapping WHERE camera_id=:c AND is_active=TRUE"),
                {"c": cam})).scalar_one()

    g1, g2, g3 = await cam_global("cam1"), await cam_global("cam2"), await cam_global("cam3")
    assert g2 == g3  # Cam2 + Cam3 -> one Global ID
    assert g1 != g2  # Cam1 distinct

    async with session_scope() as s:
        n_globals = (await s.execute(text("SELECT COUNT(*) FROM global_identities"))).scalar_one()
        n_canon = (await s.execute(text("SELECT COUNT(*) FROM global_tracking_history"))).scalar_one()
    assert n_globals == 2
    assert n_canon == 2  # one canonical position per global (single batch)
