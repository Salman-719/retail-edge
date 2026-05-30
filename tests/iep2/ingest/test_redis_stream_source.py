"""RedisStreamFrameSource: manifest -> WindowBatch, key parsing, S3 fetch order,
missing-key skip, ack."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from services.iep2_vision.app.ingest.redis_stream_source import (
    RedisStreamFrameSource,
    WindowBatch,
)
from tests.fakes import FakeRedisStream, FakeS3

pytestmark = pytest.mark.asyncio


def _jpeg(label: int) -> bytes:
    img = np.full((8, 8, 3), label, dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _manifest(bn=0, keys=None, status="online"):
    return {
        "schema_version": 1, "camera_id": "cam1", "store_id": "store",
        "batch_number": bn, "window_start_ms": 0, "window_end_ms": 60_000,
        "camera_status": status, "expected_frames": 300, "captured_frames": len(keys or []),
        "frame_keys": keys or [], "gaps": [],
    }


async def test_windows_yields_parsed_batch_and_msgid():
    redis = FakeRedisStream()
    await redis.xadd("stream:iep1:cam1", {"manifest": json.dumps(_manifest(0, ["frames/cam1/1000.jpg"]))})
    src = RedisStreamFrameSource("cam1", s3_client=FakeS3(), redis_client=redis)

    gen = src.windows()
    batch, msg_id = await gen.__anext__()
    assert isinstance(batch, WindowBatch)
    assert batch.batch_number == 0
    assert batch.frame_keys == ["frames/cam1/1000.jpg"]
    assert msg_id is not None
    await gen.aclose()


async def test_fetch_frames_in_chronological_order_skip_missing():
    s3 = FakeS3()
    # insert out of order; one key intentionally missing from S3
    await s3.put_bytes("frames/cam1/3000.jpg", _jpeg(3))
    await s3.put_bytes("frames/cam1/1000.jpg", _jpeg(1))
    # 2000 is referenced by the manifest but never uploaded -> should be skipped
    batch = WindowBatch(0, 0, 60_000, "online", 300, 3,
                        frame_keys=["frames/cam1/3000.jpg", "frames/cam1/2000.jpg", "frames/cam1/1000.jpg"],
                        gaps=[])
    src = RedisStreamFrameSource("cam1", s3_client=s3, redis_client=FakeRedisStream())

    got = [ts async for ts, _frame in src.fetch_frames(batch)]
    assert got == [1000, 3000]  # chronological, missing 2000 skipped


async def test_ack_delegates_to_redis():
    redis = FakeRedisStream()
    src = RedisStreamFrameSource("cam1", s3_client=FakeS3(), redis_client=redis)
    await src.ack(b"5-0")  # must not raise (FakeRedisStream.xack returns 1)
