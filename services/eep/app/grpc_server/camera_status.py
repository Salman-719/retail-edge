"""Camera status store for edge agents.

Tracks two things:
  _statuses        — latest {status, timestamp_ms} per camera (in-memory, for REST)
  _running_cameras — set of (store_id, physical_camera_id) currently running
                     persisted to Redis SET "running_cameras" so EEP restart
                     does not lose the feedback loop (R5).

Keys use physical_camera_id (UUID string), not camera_config_id.
The scheduler has its own _running_cameras keyed by camera_config_id.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

_REDIS_KEY = "running_cameras"

_statuses:         dict[tuple[str, str], dict] = {}
_running_cameras:  set[tuple[str, str]]         = set()

_pool: aioredis.ConnectionPool | None = None


def _redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        from app.core.config import settings as _s
        _pool = aioredis.ConnectionPool.from_url(_s.REDIS_URL, decode_responses=False)
    return aioredis.Redis(connection_pool=_pool)


# ── In-memory status (display / REST) ─────────────────────────────────────────

def update(store_id: str, camera_id: str, status: str, timestamp_ms: int) -> None:
    _statuses[(store_id, camera_id)] = {"status": status, "timestamp_ms": timestamp_ms}


def get_for_store(store_id: str) -> dict[str, dict]:
    """Return {camera_id: {status, timestamp_ms}} for every camera in the store."""
    return {
        cam_id: data
        for (s_id, cam_id), data in _statuses.items()
        if s_id == store_id
    }


def get(store_id: str, camera_id: str) -> dict | None:
    """Return {status, timestamp_ms} for a single camera, or None if never reported."""
    return _statuses.get((store_id, camera_id))


# ── Running-camera set (R4 / R5) ──────────────────────────────────────────────

async def mark_running(store_id: str, camera_id: str) -> None:
    """Mark camera as running. Persists to Redis atomically."""
    key = f"{store_id}:{camera_id}"
    _running_cameras.add((store_id, camera_id))
    try:
        await _redis().sadd(_REDIS_KEY, key)
    except Exception as exc:
        log.warning("mark_running: Redis write failed  camera=%s: %s", camera_id, exc)


async def mark_stopped(store_id: str, camera_id: str) -> None:
    """Mark camera as stopped. Persists to Redis atomically."""
    key = f"{store_id}:{camera_id}"
    _running_cameras.discard((store_id, camera_id))
    try:
        await _redis().srem(_REDIS_KEY, key)
    except Exception as exc:
        log.warning("mark_stopped: Redis write failed  camera=%s: %s", camera_id, exc)


def is_running(store_id: str, camera_id: str) -> bool:
    return (store_id, camera_id) in _running_cameras


async def rebuild_running_cameras_on_startup() -> None:
    """Load _running_cameras from Redis on EEP startup (R5)."""
    try:
        members = await _redis().smembers(_REDIS_KEY)
        for m in members:
            decoded = m.decode() if isinstance(m, bytes) else m
            parts = decoded.split(":", 1)
            if len(parts) == 2:
                _running_cameras.add((parts[0], parts[1]))
        log.info("Rebuilt running_cameras from Redis: %d entries", len(_running_cameras))
    except Exception as exc:
        log.warning("rebuild_running_cameras_on_startup failed: %s", exc)
