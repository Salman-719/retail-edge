"""StateManager — GlobalID lifecycle transitions and batch cleanup.
Runs after Process 2 inside the Reconciler's single transaction.
Uses capture-time timestamps exclusively. Never datetime.now().
"""
from __future__ import annotations

import logging
import uuid

import asyncpg

from app.repository import Iep3Repository
from app.settings import Iep3Settings

logger = logging.getLogger(__name__)


class StateManager:

    def __init__(
        self,
        repo: Iep3Repository,
        settings: Iep3Settings,
    ) -> None:
        self._repo = repo
        self._settings = settings

    async def run_cleanup(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        window_start_ms: int,
        window_end_ms: int,
    ) -> dict:
        """Run all state transitions for this batch.

        Called after Process 2 (position writing) completes.
        Returns stats dict for Reconciler logging.

        Order is strict:
          1. ACTIVE → LOST   (uses window_start_ms for activity check)
          2. LOST  → EXITED  (uses window_end_ms and grace_seconds)
          3. Deactivate mappings for exited GlobalIDs
          4. Delete centroids for exited GlobalIDs

        Newly LOST GlobalIDs (lost_since_ts = window_end_ms) will NOT exit
        this same batch: (window_end_ms - window_end_ms) = 0 < grace_ms.
        """
        # 1. ACTIVE → LOST
        lost_ids = await self._repo.transition_active_to_lost(
            conn=conn,
            store_id=store_id,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
        )
        if lost_ids:
            logger.info(
                "State: ACTIVE→LOST %d GlobalIDs "
                "(no active link seen since window_start=%d)",
                len(lost_ids), window_start_ms,
            )

        # 2. LOST → EXITED
        exited_ids = await self._repo.transition_lost_to_exited(
            conn=conn,
            store_id=store_id,
            grace_seconds=self._settings.grace_seconds,
            window_end_ms=window_end_ms,
        )
        if exited_ids:
            logger.info(
                "State: LOST→EXITED %d GlobalIDs "
                "(grace_seconds=%.0f elapsed)",
                len(exited_ids), self._settings.grace_seconds,
            )

        # 3. Deactivate mapping links for exited GlobalIDs
        # Must run before centroid deletion — delete_centroids_for_globals reads
        # global_local_mapping (including now-inactive rows) to find local_ids
        if exited_ids:
            await self._repo.deactivate_mappings_for_globals(
                conn=conn,
                global_ids=exited_ids,
                unlinked_at_ts=window_end_ms,
            )

        # 4. Delete local_centroids for LocalIDs linked to exited GlobalIDs
        if exited_ids:
            await self._repo.delete_centroids_for_globals(
                conn=conn,
                global_ids=exited_ids,
            )

        return {
            "newly_lost":   len(lost_ids),
            "newly_exited": len(exited_ids),
        }
