"""Reconciler — owns the batch transaction and orchestrates all processes.
All sub-components receive the same conn and run inside one transaction.
"""
from __future__ import annotations

import logging
import time

from app.db import get_pool
from app.metrics import (
    IEP3_BATCHES,
    IEP3_MATCHES,
    IEP3_NEW,
    IEP3_RECONCILE,
    IEP3_TRANSITIONS,
)
from app.reader import BatchReader
from app.reid.matcher import ReidMatcher
from app.repository import Iep3Repository
from app.selection import PositionSelector
from app.state import StateManager
from app.settings import Iep3Settings

logger = logging.getLogger(__name__)


class Reconciler:

    def __init__(
        self,
        store_id: str,
        repo: Iep3Repository,
        settings: Iep3Settings,
    ) -> None:
        self._store_id = store_id
        self._pool     = get_pool()   # module-level pool — must be created before __init__
        self._settings = settings
        self._repo     = repo

        # R4: count batches to trigger periodic orphan sweep
        self._batches_processed: int = 0

        # Sub-components constructed once, reused across all batches.
        # PositionSelector._resolution_cache is intentionally long-lived.
        self._reader  = BatchReader(repo)
        self._matcher = ReidMatcher(
            repo=repo,
            reid_threshold=settings.reid_threshold,
            max_speed_mps=settings.max_speed_mps,
            embedding_dim=settings.embedding_dim,
        )
        self._selector = PositionSelector(repo=repo, settings=settings)
        self._state    = StateManager(repo=repo, settings=settings)

    async def process_batch(
        self,
        batch_number: int,
        window: tuple[int, int],
        reporting_cameras: frozenset,
    ) -> dict:
        """Run one full reconciliation cycle atomically.

        Called by BatchCoordinator.on_ready. One pool.acquire(), one
        conn.transaction() — all four sub-components share the same conn.

        reporting_cameras: cameras that sent batch_complete. Used for
        logging and the partial flag only — DB reads cover all available
        data regardless of which cameras reported.

        Exceptions propagate to coordinator._fire() which catches and logs.
        No retry — a failed batch is skipped; orphan sweep on next restart
        handles any partial state.
        """
        window_start_ms, window_end_ms = window
        t0 = time.monotonic()
        # R1: partial logging moved to coordinator._fire (R6); reconciler
        # always processes whatever cameras reported — no special-casing.

        logger.info(
            "Reconciler starting batch=%d window=[%d, %d] cameras=%s",
            batch_number, window_start_ms, window_end_ms,
            sorted(reporting_cameras),
        )

        async with self._pool.acquire() as conn:
            async with conn.transaction():

                # ── Process 1: Classify and link LocalIDs ─────────────
                known, new = await self._reader.classify(
                    conn=conn,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )

                n_new_globals = await self._matcher.link_new_locals(
                    conn=conn,
                    store_id=self._store_id,
                    new_observations=new,
                    batch_number=batch_number,
                    window_end_ms=window_end_ms,
                )

                # ── Process 2: Canonical position selection ────────────
                # selector internally calls standalone repo methods that
                # acquire their own connections — correct, they read
                # EEP-owned tables outside the IEP3 transaction.
                n_written = await self._selector.write_canonical_positions(
                    conn=conn,
                    store_id=self._store_id,
                    batch_number=batch_number,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )

                # ── Cleanup: State machine transitions ─────────────────
                cleanup_stats = await self._state.run_cleanup(
                    conn=conn,
                    store_id=self._store_id,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )

        # ── tracking_history cleanup (SPEC-002) ──────────────────────────────
        # IEP3 owns tracking_history deletion, and only AFTER its batch
        # transaction has committed — on a separate connection, never inside the
        # global_tracking_history insert transaction. This closes the prior race
        # where reads/deletes of tracking_history could overlap. Non-fatal:
        # leftover rows are re-deleted when the window is next processed (IEP2
        # inserts use ON CONFLICT DO NOTHING). reporting_cameras are the physical
        # camera UUID strings that sent batch_complete for this window.
        if reporting_cameras:
            try:
                deleted = await self._repo.delete_tracking_history_window(
                    camera_ids=list(reporting_cameras),
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )
                logger.debug(
                    "Deleted %d tracking_history rows for batch=%d window=[%d, %d]",
                    deleted, batch_number, window_start_ms, window_end_ms,
                )
            except Exception:
                logger.exception(
                    "tracking_history cleanup failed for batch=%d — rows remain, "
                    "will retry on next processing of this window",
                    batch_number,
                )

        # Transaction committed. Build and log stats.
        reconcile_elapsed = time.monotonic() - t0
        self._batches_processed += 1
        stats = {
            "batch_number":        batch_number,
            "window_start_ms":     window_start_ms,
            "window_end_ms":       window_end_ms,
            "reporting_cameras":   sorted(reporting_cameras),
            "known_locals":        len(known),
            "new_locals":          len(new),
            "new_globals_created": n_new_globals,
            "positions_written":   n_written,
            **cleanup_stats,
        }

        # Prometheus metrics (job "iep3", scraped on :9300). Updated after a
        # successful commit so a rolled-back batch isn't counted.
        IEP3_BATCHES.inc()
        IEP3_RECONCILE.observe(reconcile_elapsed)
        IEP3_MATCHES.inc(len(known))
        IEP3_NEW.inc(n_new_globals)
        IEP3_TRANSITIONS.labels(transition="lost").inc(cleanup_stats.get("newly_lost", 0))
        IEP3_TRANSITIONS.labels(transition="exited").inc(cleanup_stats.get("newly_exited", 0))

        logger.info("Batch %d reconciled: %s", batch_number, stats)

        # R4: periodic orphan sweep — every ORPHAN_SWEEP_INTERVAL_BATCHES batches
        # R7: skip sweep when reconciliation consumed >80% of the window to avoid
        # extending the processing window and causing the next batch to be late.
        if self._batches_processed % self._settings.orphan_sweep_interval_batches == 0:
            sweep_budget = self._settings.window_seconds * 0.8
            if reconcile_elapsed < sweep_budget:
                try:
                    await self._repo.orphan_sweep(self._store_id)
                except Exception:
                    logger.exception(
                        "Periodic orphan sweep failed at batch=%d — skipping",
                        batch_number,
                    )
            else:
                logger.info(
                    "Skipping orphan sweep — reconciliation took %.1fs (>80%% of %.0fs window)",
                    reconcile_elapsed, self._settings.window_seconds,
                )

        return stats
