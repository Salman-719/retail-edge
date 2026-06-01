import asyncio
import json
import logging
from typing import Awaitable, Callable

log = logging.getLogger("live_bridge.redis_reader")

_STREAM_PREFIX = "stream:iep2:live"


async def read_camera_stream(
    camera_id: str,
    redis_url: str,
    on_message: Callable[[dict], Awaitable[None]],
) -> None:
    """Read stream:iep2:live:{camera_id} forever, calling on_message per frame.

    Starts from '$' (only new messages). Retries on connection errors.
    Exits cleanly on asyncio.CancelledError.
    """
    import redis.asyncio as aioredis

    stream_key = f"{_STREAM_PREFIX}:{camera_id}"
    last_id = "$"

    while True:
        client = aioredis.Redis.from_url(redis_url)
        try:
            while True:
                response = await client.xread(
                    {stream_key: last_id},
                    block=1000,
                    count=10,
                )
                if not response:
                    continue
                for _stream, messages in response:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        raw = fields.get(b"data") or fields.get("data")
                        if raw is None:
                            continue
                        try:
                            payload = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        await on_message(payload)
        except asyncio.CancelledError:
            await client.aclose()
            raise
        except Exception as exc:
            log.warning("Redis error camera=%s: %s — retrying in 2s", camera_id, exc)
            try:
                await client.aclose()
            except Exception:
                pass
            await asyncio.sleep(2)
