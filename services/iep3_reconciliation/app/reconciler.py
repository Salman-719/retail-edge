"""Reconciler -- orchestrates one batch: read -> Process 1 -> Process 2 ->
cleanup, with the write phase in a single transaction so a batch is atomic."""

from __future__ import annotations

from time import perf_counter

from common.db.engine import session_scope
from services.iep3_reconciliation.app import metrics
from services.iep3_reconciliation.app.reader import BatchReader
from services.iep3_reconciliation.app.reid.matcher import ReidMatcher
from services.iep3_reconciliation.app.selection import PositionSelector
from services.iep3_reconciliation.app.state import StateManager


class Reconciler:
    def __init__(self, store_id, repo, settings, frame_px: dict[str, int]):
        self._store, self._repo, self._s = store_id, repo, settings
        self._reader = BatchReader()
        self._matcher = ReidMatcher(repo, settings)
        self._selector = PositionSelector(repo, settings, frame_px)
        self._state = StateManager(repo, settings)

    async def process_batch(self, batch_number: int, window: tuple[int, int]) -> dict:
        t0 = perf_counter()
        window_start, window_end = window
        observations = await self._reader.read_window(window_start, window_end)

        async with session_scope() as session:
            new_obs = []
            for obs in observations:
                mapping = await self._repo.active_mapping_for(session, obs.local_id)
                if mapping:
                    await self._repo.touch_link(session, obs.local_id, batch_number)
                else:
                    new_obs.append(obs)

            await self._matcher.link_new_locals(session, self._store, new_obs, batch_number)
            n_written = await self._selector.write_canonical_positions(
                session, self._store, batch_number, window_start, window_end
            )
            cleanup = await self._state.run_cleanup(session, batch_number)

        metrics.reconcile_latency.observe(perf_counter() - t0)
        metrics.positions_written.inc(n_written)
        return {
            "observations": len(observations),
            "new_locals": len(new_obs),
            "positions_written": n_written,
            **cleanup,
        }
