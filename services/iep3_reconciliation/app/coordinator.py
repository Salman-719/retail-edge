"""BatchCoordinator — consumes stream:iep2:batch_complete.
Fires reconciliation when all expected cameras report the same batch,
or after coordinator_timeout_s when at least one camera is missing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Type alias for the reconciliation callback
OnReadyCallback = Callable[
    [int, tuple[int, int], frozenset],   # batch, window, reporting_cameras
    Awaitable[None],
]

STREAM = "stream:iep2:batch_complete"


class BatchCoordinator:

    def __init__(
        self,
        redis_client: aioredis.Redis,
        store_id: str,
        expected_cameras: frozenset,
        on_ready: OnReadyCallback,
        coordinator_timeout_s: float = 120.0,
    ) -> None:
        self._redis    = redis_client
        self._store_id = store_id
        self._expected = expected_cameras
        self._on_ready = on_ready
        self._timeout_s = coordinator_timeout_s

        # Consumer group scoped to this store — each IEP3 instance gets a
        # full independent copy of the stream via its own group.
        self._group    = f"iep3-{store_id}"
        self._consumer = "coordinator-1"

        # Batch tracking state — keyed by batch_number (int)
        self._seen:           dict[int, set[str]]       = defaultdict(set)
        self._windows:        dict[int, tuple[int, int]] = {}
        self._first_received: dict[int, float]           = {}  # time.monotonic()

    async def run(self) -> None:
        """Main coordination loop. Runs until cancelled.
        Call from main.py after orphan sweep.
        """
        await self._ensure_group()
        logger.info(
            "BatchCoordinator started — store=%s group=%s expecting cameras=%s",
            self._store_id,
            self._group,
            sorted(self._expected),
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
        """Process one batch_complete message.

        XACK fires before the callback to avoid redelivery on reconciliation
        crash. State cleanup also happens before the callback so that a slow
        callback does not cause _check_timeouts to double-fire.
        """
        try:
            store_id  = fields[b"store_id"].decode()
            camera_id = fields[b"camera_id"].decode()
            batch     = int(fields[b"batch_number"])
            start_ms  = int(fields[b"window_start_ms"])
            end_ms    = int(fields[b"window_end_ms"])
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed batch_complete message %s: %s", msg_id, exc)
            await self._redis.xack(STREAM, self._group, msg_id)
            return

        # XACK immediately — before any state change or callback
        await self._redis.xack(STREAM, self._group, msg_id)

        # Filter: silently discard messages from other stores
        if store_id != self._store_id:
            return

        # Deduplication: same camera reporting same batch twice (IEP2 replay)
        if camera_id in self._seen[batch]:
            logger.debug(
                "Duplicate batch_complete: camera=%s batch=%d — ignored",
                camera_id, batch,
            )
            return

        # Record first arrival time for timeout guard (monotonic, not timestamp_ms)
        if batch not in self._first_received:
            self._first_received[batch] = time.monotonic()
            self._windows[batch] = (start_ms, end_ms)

        self._seen[batch].add(camera_id)

        logger.info(
            "batch_complete: camera=%s batch=%d (%d/%d cameras reported)",
            camera_id, batch,
            len(self._seen[batch]), len(self._expected),
        )

        if self._expected.issubset(self._seen[batch]):
            await self._fire(batch, full=True)

    async def _check_timeouts(self) -> None:
        """Fire partial reconciliation for batches that have waited too long.

        Called on every loop iteration — including when XREADGROUP times out —
        so partial reconciliation fires even when no new messages arrive.
        """
        now = time.monotonic()
        timed_out = [
            batch
            for batch, first_ts in list(self._first_received.items())
            if (now - first_ts) >= self._timeout_s
            and not self._expected.issubset(self._seen[batch])
        ]
        for batch in timed_out:
            missing = self._expected - self._seen[batch]
            logger.warning(
                "Coordinator timeout for batch=%d after %.0fs — "
                "missing cameras=%s — firing partial reconciliation",
                batch, self._timeout_s, sorted(missing),
            )
            await self._fire(batch, full=False)

    async def _fire(self, batch: int, full: bool) -> None:
        """Fire the reconciliation callback and clean up batch tracking state.

        State cleanup happens before awaiting the callback — prevents
        _check_timeouts from double-firing if the callback is slow.
        """
        window    = self._windows.get(batch, (0, 0))
        reporting = frozenset(self._seen[batch])

        # Clean up before awaiting callback
        self._seen.pop(batch, None)
        self._windows.pop(batch, None)
        self._first_received.pop(batch, None)

        logger.info(
            "Firing reconciliation: batch=%d window=[%d,%d] cameras=%s full=%s",
            batch, window[0], window[1], sorted(reporting), full,
        )

        try:
            await self._on_ready(batch, window, reporting)
        except Exception as exc:
            logger.error(
                "Reconciliation failed for batch=%d: %s",
                batch, exc, exc_info=True,
            )
            # Do not re-raise. A failed batch is logged and skipped.
            # The next batch will run normally.
