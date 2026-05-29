"""Coordinator -- consumes IEP2 ``batch_complete`` events and triggers
reconciliation only when ALL registered cameras have reported the same batch
(IEP3 spec §2).

Late/missing camera handling: if a camera never reports (crash), a timeout guard
triggers partial reconciliation with the cameras that did report (and logs the
missing ones) rather than stalling forever -- mirroring the EEP "partial camera
failure" behaviour. The aggregation core (``note``/``check_timeouts``) is pure and
unit-tested; ``run`` only adapts the Redis stream to it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from time import monotonic

log = logging.getLogger(__name__)


class BatchCoordinator:
    STREAM = "stream:iep2:batch_complete"
    GROUP = "iep3-coordinator"

    def __init__(self, expected_cameras: set[str], on_ready, timeout_seconds: float | None = None,
                 redis_url: str | None = None, clock=monotonic):
        self._expected = set(expected_cameras)
        self._on_ready = on_ready  # async callback(batch_number, window)
        self._timeout = timeout_seconds
        self._redis_url = redis_url
        self._clock = clock
        self._seen: dict[int, set[str]] = defaultdict(set)
        self._windows: dict[int, tuple[int, int]] = {}
        self._first_arrival: dict[int, float] = {}

    async def note(self, batch_number: int, camera_id: str, window: tuple[int, int]) -> bool:
        """Record one camera's batch_complete. Fires ``on_ready`` (returns True)
        once every expected camera has reported this batch."""
        self._seen[batch_number].add(camera_id)
        self._windows[batch_number] = window
        self._first_arrival.setdefault(batch_number, self._clock())
        if self._expected.issubset(self._seen[batch_number]):
            await self._fire(batch_number)
            return True
        return False

    async def check_timeouts(self) -> list[int]:
        """Trigger partial reconciliation for batches that have waited longer than
        ``timeout_seconds`` without all cameras. Returns the batches fired."""
        if self._timeout is None:
            return []
        now = self._clock()
        stale = [
            b for b, t0 in self._first_arrival.items()
            if b in self._seen and (now - t0) >= self._timeout
        ]
        for b in stale:
            missing = self._expected - self._seen[b]
            log.warning("batch %s timed out; partial reconcile, missing cameras=%s", b, sorted(missing))
            await self._fire(b)
        return stale

    async def _fire(self, batch_number: int) -> None:
        window = self._windows.pop(batch_number)
        self._seen.pop(batch_number, None)
        self._first_arrival.pop(batch_number, None)
        await self._on_ready(batch_number, window)

    async def run(self) -> None:  # pragma: no cover - thin Redis adapter
        import redis.asyncio as redis

        from common.config import get_settings

        r = redis.from_url(self._redis_url or get_settings().REDIS_URL)
        try:
            await r.xgroup_create(self.STREAM, self.GROUP, id="0", mkstream=True)
        except redis.ResponseError:
            pass  # group already exists
        block_ms = int((self._timeout or 5) * 1000)
        while True:
            msgs = await r.xreadgroup(self.GROUP, "c1", {self.STREAM: ">"}, count=16, block=block_ms)
            for _stream, entries in msgs or []:
                for msg_id, fields in entries:
                    batch = int(fields[b"batch_number"])
                    cam = fields[b"camera_id"].decode()
                    window = (int(fields[b"window_start_ms"]), int(fields[b"window_end_ms"]))
                    await self.note(batch, cam, window)
                    await r.xack(self.STREAM, self.GROUP, msg_id)
            await self.check_timeouts()
