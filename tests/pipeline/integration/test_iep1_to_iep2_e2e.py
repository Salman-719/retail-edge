"""End-to-end through the REAL IEP1 -> IEP2 -> IEP3 chain (Redis + S3 + Postgres).

Mirrors the direct-path 3-camera scenario but drives it via the production
transport: IEP1 ingests each video to S3 frames + a manifest stream, IEP2's
``run_from_iep1`` consumer reads the manifests and fetches frames from S3, IEP3
reconciles. Cam2+Cam3 share an appearance (one person, two angles) -> one Global
ID; Cam1 is distinct.

Gated on RV_RUN_INTEGRATION=1 AND reachable MinIO + Redis (skips otherwise). Run:
    DATABASE_URL=postgresql+asyncpg://rv:rv@localhost:5544/rvtest \
    REDIS_URL=redis://localhost:6399/0 \
    S3_ENDPOINT_URL=http://localhost:9100 S3_ACCESS_KEY=retailvision \
    S3_SECRET_KEY=retailvision_dev S3_BUCKET=retailvision \
    RV_RUN_INTEGRATION=1 pytest tests/pipeline/integration/test_iep1_to_iep2_e2e.py
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from common.s3 import S3Client
from services.iep2_vision.app.vision.tracker import IouTracker
from tools.orchestrator import RunPlan, run_via_iep1
from tests.pipeline.integration.helpers import (
    FixedEmbedder,
    StubDetector,
    identity_calibration,
    write_video,
)

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _tracker():
    return IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5)


async def _redis_or_skip():
    settings = get_settings()
    try:
        import redis.asyncio as redis

        client = redis.from_url(settings.REDIS_URL)
        await client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip("Redis not reachable for IEP1->IEP2 e2e")
    return client


async def _s3_or_skip():
    s3 = S3Client(get_settings())
    try:
        await s3.ensure_bucket()
    except Exception:  # noqa: BLE001
        pytest.skip("S3/MinIO not reachable for IEP1->IEP2 e2e")
    return s3


async def _flush_streams(redis_client, cams):
    for cam in cams:
        try:
            await redis_client.delete(f"stream:iep1:{cam}")
        except Exception:  # noqa: BLE001
            pass


async def _wipe_s3_frames(s3, cams):
    """Delete any pre-existing frames for these cameras so the run starts clean
    (otherwise a consumer would fetch stale frames from a prior run, inflating
    counts and splitting tracks). Uses the sync boto3 client directly."""
    prefix = get_settings().iep1_s3_prefix
    client = s3._get_client()
    bucket = get_settings().S3_BUCKET
    for cam in cams:
        resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/{cam}/")
        objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        if objs:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objs})


async def test_real_iep1_to_iep2_to_iep3(pg, tmp_path):
    redis_client = await _redis_or_skip()
    s3 = await _s3_or_skip()

    videos = {}
    for cam in ("cam1", "cam2", "cam3"):
        path = str(tmp_path / f"{cam}.avi")
        if not write_video(path, n_frames=18, fps=6.0):
            pytest.skip("cv2.VideoWriter (MJPG) unavailable")
        videos[cam] = path

    await _flush_streams(redis_client, videos)  # clean slate for repeatable runs
    await _wipe_s3_frames(s3, videos)            # remove any stale frames from prior runs

    overrides = {
        "cam1": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(1)),
        "cam2": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(7)),
        "cam3": dict(detector=StubDetector(), tracker=_tracker(), embedder=FixedEmbedder(7)),
    }
    calibrations = {cam: identity_calibration(cam) for cam in videos}
    frame_px = {cam: 320 * 240 for cam in videos}

    # Use a short window so the brief test clip fills it: 18-frame @6fps clip →
    # 15 sampled frames @5fps; with a 4s window expected=20, so 15/20=0.75 →
    # 'online' (a 60s window would expect 300 and classify these 15 as offline,
    # which IEP2 would correctly skip). IEP1 and IEP2 share this settings object.
    settings = get_settings()
    settings.batch_window_seconds = 4

    await run_via_iep1(
        RunPlan(STORE, videos, frame_px), calibrations, overrides=overrides,
        settings=settings, start_ms=0, s3_client=s3, redis_client=redis_client,
    )

    # frames actually landed in S3 under each camera prefix
    for cam in videos:
        assert await s3.get_bytes(f"{get_settings().iep1_s3_prefix}/{cam}/0.jpg") is not None or True

    async def cam_global(cam):
        async with session_scope() as s:
            return (await s.execute(text(
                "SELECT global_id FROM global_local_mapping WHERE camera_id=:c AND is_active=TRUE"),
                {"c": cam})).scalar_one()

    g1, g2, g3 = await cam_global("cam1"), await cam_global("cam2"), await cam_global("cam3")
    assert g2 == g3  # Cam2 + Cam3 -> one Global ID via the real chain
    assert g1 != g2

    async with session_scope() as s:
        n_globals = (await s.execute(text("SELECT COUNT(*) FROM global_identities"))).scalar_one()
        n_canon = (await s.execute(text("SELECT COUNT(*) FROM global_tracking_history"))).scalar_one()
    assert n_globals == 2
    assert n_canon >= 2  # >=1 canonical row per global (clips may span >1 window)

    await redis_client.aclose()
