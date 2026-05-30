"""Iep1Runtime end-to-end with fakes: capture-time windowing, EOF partial window,
batch monotonicity, frames land in S3, manifests on the stream."""

from __future__ import annotations

import json

import numpy as np
import pytest

from common.config import get_settings
from services.iep1_ingestion.app.runtime import Iep1Runtime
from tests.fakes import FakeRedisStream, FakeS3

pytestmark = pytest.mark.asyncio


class _ListSource:
    """FrameSource yielding pre-built (capture_ts, frame) tuples."""

    def __init__(self, frames):
        self._frames = frames

    def frames(self):
        yield from self._frames

    def is_available(self):
        return True


def _frame(v=0):
    return np.full((4, 4, 3), v % 255, dtype=np.uint8)


async def _run(frames, start_ms=0):
    s3, redis = FakeS3(), FakeRedisStream()
    rt = Iep1Runtime("store", "cam1", get_settings(), s3_client=s3, redis_client=redis)
    result = await rt.run(_ListSource(frames), start_ms)
    manifests = [json.loads(f[b"manifest"]) for _id, f in redis._streams.get("stream:iep1:cam1", [])]
    return result, s3, manifests


async def test_single_window_frames_in_s3_and_one_manifest():
    # 10 frames within the first 60s window (200ms apart)
    frames = [(i * 200, _frame(i)) for i in range(10)]
    result, s3, manifests = await _run(frames)
    assert len(manifests) == 1                 # one partial window at EOF
    assert manifests[0]["captured_frames"] == 10
    assert len(s3.store) == 10                  # every frame uploaded
    assert all(k.startswith("frames/cam1/") for k in s3.store)
    assert result["last_batch_number"] == 0


async def test_capture_time_drives_window_boundaries_and_monotonic_batches():
    # frames spanning ~2.5 windows: 0s, 30s, 65s, 125s
    frames = [(0, _frame()), (30_000, _frame()), (65_000, _frame()), (125_000, _frame())]
    result, _s3, manifests = await _run(frames)
    batch_numbers = [m["batch_number"] for m in manifests]
    assert batch_numbers == sorted(batch_numbers)            # monotonic
    assert batch_numbers == list(range(len(batch_numbers)))  # dense, no skips
    assert len(manifests) >= 3                                # at least 3 windows touched
    # window 0 has the 0s + 30s frames; a later window holds the 65s frame, etc.
    assert manifests[0]["window_start_ms"] == 0
    assert manifests[0]["window_end_ms"] == 60_000


async def test_long_gap_produces_offline_window_in_between():
    # one frame at 0s, then nothing until 130s -> window 1 (60-120s) is empty/offline
    frames = [(0, _frame()), (130_000, _frame())]
    _result, _s3, manifests = await _run(frames)
    statuses = {m["batch_number"]: m["camera_status"] for m in manifests}
    assert statuses[1] == "offline"            # the skipped middle window
    assert any(m["camera_status"] == "offline" for m in manifests)
