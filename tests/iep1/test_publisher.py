"""WindowPublisher: manifest round-trips through Redis serialization; buffering
when Redis is down, replay on recovery."""

from __future__ import annotations

import json

import pytest

from common.config import get_settings
from services.iep1_ingestion.app.publisher import WindowPublisher
from services.iep1_ingestion.app.window import Gap, WindowManifest
from tests.fakes import FakeRedisStream

pytestmark = pytest.mark.asyncio


def _manifest(bn=0):
    return WindowManifest(
        camera_id="cam1", store_id="store", batch_number=bn,
        window_start_ms=0, window_end_ms=60_000, camera_status="degraded",
        expected_frames=300, captured_frames=285,
        frame_keys=["frames/cam1/200.jpg", "frames/cam1/400.jpg"],
        gaps=[Gap(1000, 4000, 15)],
    )


async def test_uuid_store_id_serializes():
    import uuid

    fake = FakeRedisStream()
    pub = WindowPublisher("cam1", redis_client=fake, settings=get_settings())
    m = _manifest(0)
    m.store_id = uuid.uuid4()  # orchestrator passes a UUID, not a str
    assert await pub.publish(m) is True
    payload = json.loads(fake._streams["stream:iep1:cam1"][0][1][b"manifest"])
    assert payload["store_id"] == str(m.store_id)


async def test_manifest_round_trips_one_message_per_window():
    fake = FakeRedisStream()
    pub = WindowPublisher("cam1", redis_client=fake, settings=get_settings())
    assert await pub.publish(_manifest(0)) is True
    assert await pub.publish(_manifest(1)) is True

    assert fake.message_count("stream:iep1:cam1") == 2
    _id, fields = fake._streams["stream:iep1:cam1"][0]
    payload = json.loads(fields[b"manifest"])
    assert payload["camera_id"] == "cam1"
    assert payload["batch_number"] == 0
    assert payload["gaps"][0]["missing_frames"] == 15  # Gap serialized as dict
    assert payload["frame_keys"][0] == "frames/cam1/200.jpg"


class _BrokenThenOkRedis(FakeRedisStream):
    def __init__(self, fail_times: int):
        super().__init__()
        self._fail = fail_times

    async def xadd(self, stream, fields):
        if self._fail > 0:
            self._fail -= 1
            raise ConnectionError("redis down")
        return await super().xadd(stream, fields)


async def test_buffers_when_redis_down_then_replays():
    redis = _BrokenThenOkRedis(fail_times=1)
    pub = WindowPublisher("cam1", redis_client=redis, settings=get_settings())
    assert await pub.publish(_manifest(0)) is False  # buffered
    assert redis.message_count("stream:iep1:cam1") == 0
    assert await pub.publish(_manifest(1)) is True    # drains buffer + sends new
    assert redis.message_count("stream:iep1:cam1") == 2
