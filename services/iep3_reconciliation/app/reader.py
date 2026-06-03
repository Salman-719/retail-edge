"""BatchReader — reads and classifies LocalIDs for a batch window.
Operates inside the Reconciler's single transaction (conn passed by caller).
"""
from __future__ import annotations

import logging
import uuid

import asyncpg

from app.repository import Iep3Repository, LocalObservation

logger = logging.getLogger(__name__)


class BatchReader:

    def __init__(self, repo: Iep3Repository) -> None:
        self._repo = repo

    async def classify(
        self,
        conn: asyncpg.Connection,
        window_start_ms: int,
        window_end_ms: int,
    ) -> tuple[list[LocalObservation], list[LocalObservation]]:
        """Read all LocalIDs in the batch window and classify as known or new.

        Returns:
            known: LocalIDs with an active global_local_mapping row.
                   last_seen_ts updated via touch_links_bulk (one query).
                   Ordered by first_seen_ts ASC.
            new:   LocalIDs with no active mapping.
                   Ordered by first_seen_ts ASC — deterministic ReID order.

        Total: 3 queries per batch regardless of observation count (no N+1).
        """
        # 1. Load all observations in this window (ordered by first_seen_ts ASC)
        observations = await self._repo.read_batch_observations(
            conn, window_start_ms, window_end_ms
        )

        if not observations:
            logger.debug(
                "BatchReader: no observations in window [%d, %d]",
                window_start_ms, window_end_ms,
            )
            return [], []

        # 2. Bulk-load active mappings for all observed LocalIDs (one query)
        all_local_ids = [obs.local_id for obs in observations]
        mapping_map = await self._repo.get_active_mappings_bulk(
            conn, all_local_ids
        )

        # 3. Classify in Python — preserves first_seen_ts ordering from query
        known: list[LocalObservation] = []
        new:   list[LocalObservation] = []

        for obs in observations:
            if obs.local_id in mapping_map:
                known.append(obs)
            else:
                new.append(obs)

        # 4. Bulk touch-link all known LocalIDs (one query via unnest)
        if known:
            await self._repo.touch_links_bulk(
                conn,
                [(obs.local_id, obs.last_seen_ts) for obs in known],
            )

        logger.info(
            "BatchReader: window=[%d,%d] total=%d known=%d new=%d",
            window_start_ms, window_end_ms,
            len(observations), len(known), len(new),
        )

        # new is already ordered by first_seen_ts ASC from read_batch_observations
        # (ORDER BY MIN(timestamp_ms) ASC in the query) — do not re-sort
        return known, new
