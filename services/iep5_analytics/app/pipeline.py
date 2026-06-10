"""IEP5 pipeline: preflight checks, build the run context, then run every
aggregator inside ONE transaction. Returns a process exit code.
"""
from __future__ import annotations

import logging

from app.aggregators import employees, heatmap, rollups, sequences, visits, zones
from app.context import RunContext, day_bounds_ms, rollup_params
from app.db import get_pool
from app.metrics import IEP5_GTH_ROWS
from app.persistence.postgres import AnalyticsRepository
from app.settings import Iep5Settings

logger = logging.getLogger(__name__)


class AnalyticsPipeline:
    def __init__(self, settings: Iep5Settings, repo: AnalyticsRepository) -> None:
        self._s = settings
        self._repo = repo

    async def run(self) -> int:
        s = self._s
        day_start_ms, day_end_ms = day_bounds_ms(s.shift_date)

        # ── Preflight ─────────────────────────────────────────────────────────
        # Already completed for this (store, date) — idempotent no-op, exit 0.
        if await self._repo.daily_summary_exists(s.shift_date):
            logger.info("IEP5: daily_store_summary already exists for store=%s date=%s — "
                        "already completed, exiting 0", s.store_id, s.shift_date)
            return 0

        open_visits = await self._repo.count_open_visits()
        if open_visits > 0:
            logger.error("IEP5 preflight FAILED: %d open visit_sessions for store=%s — "
                         "EEP closing sequence did not run", open_visits, s.store_id)
            return 1

        open_aps = await self._repo.count_active_person_state()
        if open_aps > 0:
            logger.error("IEP5 preflight FAILED: active_person_state not cleared "
                         "(%d rows) for store=%s", open_aps, s.store_id)
            return 1

        gth_count = await self._repo.count_gth_in_window(day_start_ms, day_end_ms)
        IEP5_GTH_ROWS.set(gth_count)
        if gth_count == 0:
            logger.warning("IEP5: no global_tracking_history for store=%s date=%s — "
                           "empty shift (valid), writing zero summaries", s.store_id, s.shift_date)

        # ── Shift bounds ──────────────────────────────────────────────────────
        shift_start_ms, shift_end_ms = await self._repo.shift_bounds(day_start_ms, day_end_ms)
        if shift_start_ms is None:
            shift_start_ms, shift_end_ms = day_start_ms, day_end_ms

        version_id, origin_x, origin_y = await self._repo.active_version_origin()

        (iso_year, iso_week, week_start_date, is_week_complete,
         year, month, month_start_date, is_month_complete) = rollup_params(s.shift_date)

        ctx = RunContext(
            store_id=self._repo.store_id, shift_date=s.shift_date,
            day_start_ms=day_start_ms, day_end_ms=day_end_ms,
            shift_start_ms=shift_start_ms, shift_end_ms=shift_end_ms,
            version_id=version_id, origin_x=origin_x, origin_y=origin_y,
            cell_size_m=s.heatmap_cell_size_m, passthrough_ms=s.passthrough_dwell_ms,
            dead_threshold=s.dead_period_threshold, dead_duration_ms=s.dead_period_duration_ms,
            iso_year=iso_year, iso_week=iso_week, week_start_date=week_start_date,
            is_week_complete=is_week_complete, year=year, month=month,
            month_start_date=month_start_date, is_month_complete=is_month_complete,
        )

        logger.info(
            "IEP5 aggregating store=%s date=%s window=[%d,%d) version=%s gth_rows=%d",
            s.store_id, s.shift_date, shift_start_ms, shift_end_ms, version_id, gth_count,
        )

        # ── All writes in ONE transaction (idempotent ON CONFLICT upserts) ────
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await visits.run(conn, ctx)        # daily_store_summary + distribution
                await zones.run(conn, ctx)         # daily_zone_summary
                await sequences.run(conn, ctx)     # zone_sequence_matrix
                await employees.run(conn, ctx)     # daily_employee_summary
                await heatmap.run(conn, ctx)       # heatmap_hourly + heatmap_daily
                await rollups.run(conn, ctx)       # weekly + monthly

        logger.info("IEP5 complete store=%s date=%s", s.store_id, s.shift_date)
        return 0
