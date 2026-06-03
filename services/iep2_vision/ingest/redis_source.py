"""Redis Stream consumer for IEP1 manifests.

Uses XREADGROUP for at-least-once delivery with crash recovery.
S3 frame fetching is NOT done here — callers receive raw manifest dicts
and handle S3 themselves.
"""
import json
import logging

import boto3
import redis.asyncio as aioredis

log = logging.getLogger("iep2.redis_source")

STREAM_PREFIX = "stream:iep1"
GROUP_NAME    = "iep2_workers"
BLOCK_MS      = 2000
READ_COUNT    = 10


def make_s3_client(endpoint_url: str, access_key: str, secret_key: str):
    kwargs = dict(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


class RedisStreamFrameSource:
    def __init__(self, camera_id: str, redis_url: str, s3_client) -> None:
        self._camera_id     = camera_id
        self._s3_client     = s3_client
        self._stream_name   = f"{STREAM_PREFIX}:{camera_id}"
        self._consumer_name = f"iep2_{camera_id}"
        self._redis_url     = redis_url
        self._redis         = None

    async def connect(self) -> None:
        self._redis = aioredis.Redis.from_url(self._redis_url)
        await self._ensure_group()
        log.info(
            "Consumer group ready  stream=%s  group=%s  consumer=%s",
            self._stream_name, GROUP_NAME, self._consumer_name,
        )

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                name=self._stream_name,
                groupname=GROUP_NAME,
                id="0",
                mkstream=True,
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def manifests(self):
        """Async generator yielding (message_id, manifest_dict).

        Phase A: drain all pending messages from before a crash (ID="0").
        Phase B: read new messages (ID=">") indefinitely.
        ACK is the caller's responsibility after the DB write succeeds.
        """
        # Phase A — crash recovery: replay any un-ACKed messages
        log.info("Phase A: draining pending messages  stream=%s", self._stream_name)
        while True:
            response = await self._redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=self._consumer_name,
                streams={self._stream_name: "0"},
                count=READ_COUNT,
                block=BLOCK_MS,
            )
            if not response:
                break
            any_yielded = False
            for _stream, messages in response:
                for message_id, fields in messages:
                    manifest = self._parse_fields(fields)
                    if manifest is None:
                        continue
                    any_yielded = True
                    yield message_id, manifest
            if not any_yielded:
                break

        log.info("Phase B: reading new messages  stream=%s", self._stream_name)

        # Phase B — normal operation: read new messages
        while True:
            response = await self._redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=self._consumer_name,
                streams={self._stream_name: ">"},
                count=READ_COUNT,
                block=BLOCK_MS,
            )
            if not response:
                continue
            for _stream, messages in response:
                for message_id, fields in messages:
                    manifest = self._parse_fields(fields)
                    if manifest is None:
                        continue
                    yield message_id, manifest

    @property
    def redis_client(self):
        """Expose the underlying Redis client for callers that need to publish to other streams."""
        return self._redis

    async def ack(self, message_id) -> None:
        """ACK a message after successful processing and DB write."""
        await self._redis.xack(self._stream_name, GROUP_NAME, message_id)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            log.info("Redis client closed  stream=%s", self._stream_name)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    @staticmethod
    def _parse_fields(fields: dict) -> dict | None:
        raw = fields.get(b"manifest") or fields.get("manifest")
        if raw is None:
            return None
        return json.loads(raw)
