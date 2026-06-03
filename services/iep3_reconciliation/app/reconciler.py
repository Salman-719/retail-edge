"""Reconciler — owns the batch transaction and orchestrates all processes.
All sub-components receive the same conn and run inside one transaction.
"""
from __future__ import annotations

import logging

from app.db import get_pool
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
        partial = reporting_cameras < self._settings.expected_cameras

        if partial:
            missing = self._settings.expected_cameras - reporting_cameras
            logger.warning(
                "Partial reconciliation for batch=%d — "
                "missing cameras=%s — using available DB data",
                batch_number, sorted(missing),
            )

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

        # Transaction committed. Build and log stats.
        stats = {
            "batch_number":        batch_number,
            "window_start_ms":     window_start_ms,
            "window_end_ms":       window_end_ms,
            "reporting_cameras":   sorted(reporting_cameras),
            "partial":             partial,
            "known_locals":        len(known),
            "new_locals":          len(new),
            "new_globals_created": n_new_globals,
            "positions_written":   n_written,
            **cleanup_stats,
        }

        logger.info("Batch %d reconciled: %s", batch_number, stats)
        return stats
