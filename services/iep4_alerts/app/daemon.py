"""IEP4 main loop: batch cursor, catch-up, and the per-cycle pipeline.

Each cycle: read the delta of new batches, update active_person_state, detect
zone transitions, open/close visit sessions, then evaluate alerts. The previous
cycle's active_person_state is held in memory (dict keyed by global_id) so zone
changes are detected without a DB read.

Cursor persistence: there is no cursor table. The cursor is resumed from
max(active_person_state.last_batch_number) for this store — the furthest batch
already reflected in state. On a cold start (empty state) it begins at the
latest batch (forward-only). batch_number is window_start_ms, so batch counts
convert to batch_number via * window_ms.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.metrics import (
    IEP4_ACTIVE_PERSONS,
    IEP4_CYCLE_ERRORS,
    IEP4_CYCLE_SECONDS,
    IEP4_CYCLES,
    IEP4_VISITS_CLOSED,
    IEP4_VISITS_OPENED,
    IEP4_ZONE_TRANSITIONS,
)
from app.alerts.delivery import EmailDelivery
from app.alerts.evaluator import AlertEvaluator
from app.models import PersonState
from app.persistence.postgres import AlertRepository
from app.settings import Iep4Settings
from app.state.person_state import (
    PersonStateManager,
    compute_states,
    first_seen_map,
)
from app.state.visit_tracker import VisitTracker
from app.state.zone_tracker import ZoneTracker

logger = logging.getLogger(__name__)

_CLOSING_STATES = {"lost", "exited"}


class AlertDaemon:
    def __init__(self, settings: Iep4Settings, repo: AlertRepository) -> None:
        self._s = settings
        self._repo = repo
        self._delivery = EmailDelivery(settings)
        self._person = PersonStateManager(repo)
        self._zones = ZoneTracker(repo)
        self._visits = VisitTracker(repo, version_id=None)
        self._evaluator = AlertEvaluator(repo, settings, self._delivery)

        self._states: dict[uuid.UUID, PersonState] = {}
        self._cursor: int = 0
        self._catchup: bool = False

    # ── Bootstrap ────────────────────────────────────────────────────────────

    async def bootstrap(self) -> None:
        # Rehydrate in-memory state from active_person_state.
        rows = await self._repo.load_active_person_state()
        self._states = {
            r["global_id"]: PersonState(
                global_id=r["global_id"],
                current_zone_id=r["current_zone_id"],
                entered_current_zone_at=r["entered_current_zone_at"],
                last_seen_at=int(r["last_seen_at"]),
                last_batch_number=int(r["last_batch_number"]),
                is_employee=bool(r["is_employee"]),
                employee_id=r["employee_id"],
                entered_zone_batch=int(r["last_batch_number"]),
            )
            for r in rows
        }
        self._visits.set_version(await self._repo.get_active_version_id())

        current_max = await self._repo.get_max_batch()
        if current_max is None:
            self._cursor = 0
            logger.info("IEP4 bootstrap store=%s — no batches yet, cursor=0", self._s.store_id)
            return

        aps_max = max((s.last_batch_number for s in self._states.values()), default=None)
        if aps_max is None:
            self._cursor = current_max  # cold start — no historical replay
        else:
            gap_batches = (current_max - aps_max) / self._s.window_ms
            if gap_batches > self._s.max_lookback_batches:
                ff = current_max - self._s.max_lookback_batches * self._s.window_ms
                logger.warning(
                    "IEP4 cursor gap %.0f batches > MAX_LOOKBACK_BATCHES=%d store=%s — "
                    "fast-forwarding cursor from %d to %d (missed %d..%d)",
                    gap_batches, self._s.max_lookback_batches, self._s.store_id,
                    aps_max, ff, aps_max, ff,
                )
                self._cursor = ff
                self._catchup = True
            else:
                self._cursor = aps_max
                self._catchup = current_max > aps_max
        logger.info(
            "IEP4 bootstrap store=%s cursor=%d catchup=%s tracked=%d",
            self._s.store_id, self._cursor, self._catchup, len(self._states),
        )

    # ── Loop ─────────────────────────────────────────────────────────────────

    async def run(self, stop_event: asyncio.Event) -> None:
        await self.bootstrap()
        while not stop_event.is_set():
            _t0 = time.monotonic()
            try:
                await self._tick()
            except Exception:
                IEP4_CYCLE_ERRORS.inc()
                logger.exception("IEP4 cycle failed — continuing")
            finally:
                IEP4_CYCLES.inc()
                IEP4_CYCLE_SECONDS.observe(time.monotonic() - _t0)

            if self._catchup:
                delay = 0.2  # drain backlog quickly
            else:
                delay = self._s.window_seconds * self._s.evaluation_batches
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        # NEVER evaluate without an active store config version.
        if not await self._repo.has_active_version():
            return

        # 1. Advance state for any new batches.
        current_max = await self._repo.get_max_batch()
        if current_max is not None and current_max > self._cursor:
            if self._catchup:
                to_batch = min(
                    self._cursor + self._s.catchup_batch_size * self._s.window_ms,
                    current_max,
                )
            else:
                to_batch = current_max

            await self._process_window(self._cursor, to_batch)
            self._cursor = to_batch

            if self._cursor >= current_max and self._catchup:
                logger.info("IEP4 catch-up complete store=%s cursor=%d", self._s.store_id, self._cursor)
                self._catchup = False

        # 2. Evaluate alerts every cycle, AFTER active_person_state is updated —
        #    so cooldown/followup/auto-resolve timers progress in real time even
        #    across cycles with no new batches.
        now_ms = int(time.time() * 1000)
        await self._evaluator.run(now_ms)

    # ── One window ───────────────────────────────────────────────────────────

    async def _process_window(self, from_batch: int, to_batch: int) -> None:
        self._visits.set_version(await self._repo.get_active_version_id())

        delta = await self._repo.get_delta(from_batch, to_batch)
        present_ids = {r.global_id for r in delta}
        new_states = compute_states(delta, self._states)
        first_seen = first_seen_map(delta)
        new_global_ids = [gid for gid in new_states if gid not in self._states]

        # 1. Zone transitions (prev -> new) BEFORE we overwrite in-memory state.
        n_trans = await self._zones.process(self._states, new_states)

        # 2. active_person_state bulk upsert.
        await self._person.persist(new_states)

        # 3. Open visits for first-seen persons.
        n_open = await self._visits.open_new(new_global_ids, new_states, first_seen)

        # 4. Handle disappearances — only close/remove when IEP3 has marked the
        #    person LOST/EXITED. Order: close visit -> delete aps -> drop memory.
        absent = [gid for gid in self._states if gid not in present_ids]
        n_closed = 0
        if absent:
            gstate = await self._repo.get_global_states(absent)
            to_close = [gid for gid in absent if gstate.get(gid) in _CLOSING_STATES]
            for gid in to_close:
                prev = self._states[gid]
                await self._visits.close(gid, prev.last_seen_at)
            await self._person.delete(to_close)
            for gid in to_close:
                self._states.pop(gid, None)
            n_closed = len(to_close)

        # 5. Refresh in-memory state for present persons.
        self._states.update(new_states)

        IEP4_ZONE_TRANSITIONS.inc(n_trans)
        IEP4_VISITS_OPENED.inc(n_open)
        IEP4_VISITS_CLOSED.inc(n_closed)
        IEP4_ACTIVE_PERSONS.set(len(self._states))

        logger.info(
            "IEP4 cycle store=%s window=(%d,%d] delta=%d transitions=%d visits_opened=%d "
            "visits_closed=%d tracked=%d",
            self._s.store_id, from_batch, to_batch, len(delta), n_trans,
            n_open, n_closed, len(self._states),
        )
