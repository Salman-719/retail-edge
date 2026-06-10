"""BatchCoordinator — consumes stream:iep2:batch_complete.
Fires reconciliation when all expected cameras report the same batch,
or after coordinator_timeout_s when at least one camera is missing.

R1: Expected cameras sourced from DB (not env var) and refreshed periodically.
R8: Batches grouped by window_start_ms rounded to window boundary — restart-safe.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.metrics import IEP3_ERRORS
from collections import defaultdict
from typing import Awaitable, Callable

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def check_pel_health(redis_client: aioredis.Redis, store_id: str) -> int:
    """Check pending entries in the IEP3 consumer group.

    In the XACK-before-processing model the PEL must always be empty on startup.
    A non-empty PEL means XACK was not sent in a previous session — which
    should be impossible and indicates a code bug or Redis client issue.
    Returns 0 if the group does not yet exist (first startup before coordinator runs).
    """
    group = f"iep3-{store_id}"
    try:
        info = await redis_client.xpending(STREAM, group)
        pending_count = int(info["pending"])
    except aioredis.ResponseError:
        # Group does not exist yet — first startup, no PEL possible.
        pending_count = 0

    if pending_count > 0:
        logger.warning(
            "Non-empty PEL for IEP3 store=%s pending=%d — investigate XACK logic",
            store_id, pending_count,
        )
    else:
        logger.info("PEL health: 0 pending entries for group %s", group)
    return pending_count


# Type alias for the reconciliation callback
OnReadyCallback = Callable[
    [int, tuple[int, int], frozenset],   # batch_key, window, reporting_cameras
    Awaitable[None],
]

STREAM = "stream:iep2:batch_complete"


class BatchCoordinator:

    def __init__(
        self,
        redis_client: aioredis.Redis,
        store_id: str,
        expected_cameras: int,
        on_ready: OnReadyCallback,
        coordinator_timeout_s: float = 120.0,
        pool: asyncpg.Pool | None = None,
        window_seconds: float = 60.0,
        expected_cameras_refresh_batches: int = 10,
    ) -> None:
        self._redis    = redis_client
        self._store_id = store_id
        self._on_ready = on_ready
        self._timeout_s = coordinator_timeout_s
        self._pool      = pool
        self._window_seconds = window_seconds
        self._refresh_batches = expected_cameras_refresh_batches

        # R1: count-based expected cameras (refreshed from DB periodically)
        self._expected_cameras: int = expected_cameras
        self._batches_since_refresh: int = 0

        # Consumer group scoped to this store — each IEP3 instance gets a
        # full independent copy of the stream via its own group.
        self._group    = f"iep3-{store_id}"
        self._consumer = "coordinator-1"

        # R8: batch tracking keyed by _batch_key(window_start_ms), not batch_number
        self._seen:           dict[int, set[str]]        = defaultdict(set)
        self._windows:        dict[int, tuple[int, int]] = {}
        self._first_received: dict[int, float]           = {}  # time.monotonic()

    def _batch_key(self, window_start_ms: int) -> int:
        """Round window_start_ms to the nearest window boundary.

        Groups cameras that report slightly different window_start_ms values
        (due to clock skew) into the same batch. Restart-safe: batch_number
        resets to 0 on IEP1 restart, but window_start_ms is monotonic.
        """
        window_ms = int(self._window_seconds * 1000)
        return int(round(window_start_ms / window_ms) * window_ms)

    async def run(self) -> None:
        """Main coordination loop. Runs until cancelled.
        Call from main.py after orphan sweep.
        """
        await self._ensure_group()
        logger.info(
            "BatchCoordinator started — store=%s group=%s expecting cameras=%d",
            self._store_id,
            self._group,
            self._expected_cameras,
        )

        while True:
            await self._check_timeouts()

            try:
                messages = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams={STREAM: ">"},
                    count=16,
                    block=5000,  # ms — yields to event loop regularly
                )
            except aioredis.ResponseError as exc:
                if "NOGROUP" in str(exc):
                    # Stream or consumer group was deleted (Redis restart, manual
                    # flush, or first-ever publish). Recreate and continue — the
                    # next XREADGROUP will succeed without any external intervention.
                    logger.warning(
                        "Consumer group lost (stream deleted or Redis restarted) — "
                        "recreating: %s", exc,
                    )
                    await self._ensure_group()
                else:
                    logger.error("XREADGROUP error: %s — retrying in 5s", exc)
                    await asyncio.sleep(5)
                continue

            if not messages:
                continue  # block timeout, loop again → _check_timeouts()

            for _stream_name, entries in messages:
                for msg_id, fields in entries:
                    await self._handle(msg_id, fields)

    async def _ensure_group(self) -> None:
        """Create consumer group, tolerating already-exists on IEP3 restart."""
        try:
            await self._redis.xgroup_create(
                STREAM, self._group, id="0", mkstream=True
            )
            logger.info("Consumer group %s created", self._group)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                logger.info(
                    "Consumer group %s already exists — continuing", self._group
                )
            else:
                raise

    async def _handle(self, msg_id: bytes, fields: dict) -> None:
        """Process one batch_complete message."""
        try:
            store_id  = fields[b"store_id"].decode()
            camera_id = fields[b"camera_id"].decode()
            start_ms  = int(fields[b"window_start_ms"])
            end_ms    = int(fields[b"window_end_ms"])
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed batch_complete message %s: %s", msg_id, exc)
            await self._redis.xack(STREAM, self._group, msg_id)
            return

        # XACK fires here — BEFORE on_ready / reconciliation.
        #
        # Trade-off: if IEP3 crashes after XACK but before reconciliation
        # completes, the batch is lost (no retry). The compensating control
        # is orphan_sweep(), which runs on IEP3 startup and every
        # ORPHAN_SWEEP_INTERVAL_BATCHES batches to clean partial state.
        #
        # The alternative (XACK after reconciliation) risks duplicate
        # reconciliation on restart if batch_complete was already processed
        # but XACK was not sent — IEP3 has no idempotency guard for
        # full reconciliation replays. XACK-before is the lesser evil.
        await self._redis.xack(STREAM, self._group, msg_id)

        # Filter: silently discard messages from other stores
        if store_id != self._store_id:
            return

        # R8: group by window_start_ms rounded to window boundary (restart-safe)
        batch_key = self._batch_key(start_ms)

        # Deduplication: same camera reporting same batch_key twice (IEP2 replay)
        if camera_id in self._seen[batch_key]:
            logger.debug(
                "Duplicate batch_complete: camera=%s batch_key=%d — ignored",
                camera_id, batch_key,
            )
            return

        # Record first arrival time for timeout guard (monotonic, not timestamp_ms)
        if batch_key not in self._first_received:
            self._first_received[batch_key] = time.monotonic()
            self._windows[batch_key] = (start_ms, end_ms)

        self._seen[batch_key].add(camera_id)

        logger.info(
            "batch_complete: camera=%s batch_key=%d (%d/%d cameras reported)",
            camera_id, batch_key,
            len(self._seen[batch_key]), self._expected_cameras,
        )

        if len(self._seen[batch_key]) >= self._expected_cameras:
            await self._fire(batch_key)

    async def _check_timeouts(self) -> None:
        """Fire partial reconciliation for batches that have waited too long.

        Called on every loop iteration — including when XREADGROUP times out —
        so partial reconciliation fires even when no new messages arrive.
        """
        now = time.monotonic()
        timed_out = [
            batch_key
            for batch_key, first_ts in list(self._first_received.items())
            if (now - first_ts) >= self._timeout_s
            and len(self._seen[batch_key]) < self._expected_cameras
        ]
        for batch_key in timed_out:
            logger.warning(
                "Coordinator timeout for batch_key=%d after %.0fs — "
                "cameras_reported=%d expected=%d — firing partial reconciliation",
                batch_key, self._timeout_s,
                len(self._seen[batch_key]), self._expected_cameras,
            )
            await self._fire(batch_key)

    async def _fire(self, batch_key: int) -> None:
        """Fire the reconciliation callback and clean up batch tracking state.

        State cleanup happens before awaiting the callback — prevents
        _check_timeouts from double-firing if the callback is slow.
        """
        window    = self._windows.get(batch_key, (0, 0))
        reporting = frozenset(self._seen[batch_key])

        # R6: structured partial batch logging
        is_partial = len(reporting) < self._expected_cameras
        if is_partial:
            logger.warning(
                "Partial batch fired",
                extra={
                    "batch_key":        batch_key,
                    "store_id":         self._store_id,
                    "cameras_reported": len(reporting),
                    "cameras_expected": self._expected_cameras,
                    "missing_cameras":  self._expected_cameras - len(reporting),
                },
            )

        # Clean up before awaiting callback
        self._seen.pop(batch_key, None)
        self._windows.pop(batch_key, None)
        self._first_received.pop(batch_key, None)

        # R1: periodically refresh expected cameras count from DB
        self._batches_since_refresh += 1
        if self._pool is not None and self._batches_since_refresh >= self._refresh_batches:
            try:
                async with self._pool.acquire() as conn:
                    count = await conn.fetchval(
                        """
                        SELECT COUNT(cc.id)
                        FROM camera_configs cc
                        JOIN store_config_versions scv ON scv.id = cc.version_id
                        WHERE scv.store_id = $1
                          AND scv.status   = 'active'
                        """,
                        uuid.UUID(self._store_id),
                        timeout=10.0,
                    )
                    self._expected_cameras = int(count or 0)
                    logger.info("Expected cameras refreshed: %d", self._expected_cameras)
            except Exception:
                logger.warning(
                    "Failed to refresh expected_cameras — keeping current value=%d",
                    self._expected_cameras,
                )
            self._batches_since_refresh = 0

        logger.info(
            "Firing reconciliation: batch_key=%d window=[%d,%d] cameras=%s partial=%s",
            batch_key, window[0], window[1], sorted(reporting), is_partial,
        )

        try:
            await self._on_ready(batch_key, window, reporting)
        except Exception as exc:
            IEP3_ERRORS.labels(error_type=type(exc).__name__).inc()
            logger.error(
                "Reconciliation failed for batch_key=%d: %s",
                batch_key, exc, exc_info=True,
            )
            # Do not re-raise. A failed batch is logged and skipped.
            # The next batch will run normally.
