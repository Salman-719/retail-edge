"""daily_store_summary + visit_duration_distribution. Source: visit_sessions
(customers only, is_employee = FALSE). Peak occupancy + dead periods come from
occupancy.py (raw global_tracking_history)."""
from __future__ import annotations

from app.aggregators import occupancy
from app.context import RunContext

_VISIT_AGG = """
SELECT
    COUNT(*)                                                    AS total_visits,
    COUNT(DISTINCT global_id)                                   AS unique_visitors,
    AVG(total_duration_ms)::bigint                              AS avg_visit_duration_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms)::bigint
                                                                AS median_visit_duration_ms
FROM visit_sessions
WHERE store_id = $1
  AND entered_at_ms >= $2 AND entered_at_ms < $3
  AND is_employee = FALSE
  AND total_duration_ms IS NOT NULL
"""

_DAILY_STORE_UPSERT = """
INSERT INTO analytics.daily_store_summary (
    store_id, date, total_visits, unique_visitors,
    avg_visit_duration_ms, median_visit_duration_ms,
    peak_occupancy, peak_occupancy_at_ms,
    dead_period_count, dead_period_total_ms
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (store_id, date) DO UPDATE SET
    total_visits             = EXCLUDED.total_visits,
    unique_visitors          = EXCLUDED.unique_visitors,
    avg_visit_duration_ms    = EXCLUDED.avg_visit_duration_ms,
    median_visit_duration_ms = EXCLUDED.median_visit_duration_ms,
    peak_occupancy           = EXCLUDED.peak_occupancy,
    peak_occupancy_at_ms     = EXCLUDED.peak_occupancy_at_ms,
    dead_period_count        = EXCLUDED.dead_period_count,
    dead_period_total_ms     = EXCLUDED.dead_period_total_ms
"""

# visit_duration_distribution: fixed labelled buckets, one row per non-empty bucket.
_DIST_UPSERT = """
INSERT INTO analytics.visit_duration_distribution (
    store_id, date, bucket_label, bucket_min_ms, bucket_max_ms, visit_count
)
SELECT $1, $2, d.bucket_label, d.bucket_min_ms, d.bucket_max_ms, d.visit_count
FROM (
    SELECT
        CASE
            WHEN total_duration_ms < 300000  THEN '0-5min'
            WHEN total_duration_ms < 900000  THEN '5-15min'
            WHEN total_duration_ms < 1800000 THEN '15-30min'
            WHEN total_duration_ms < 3600000 THEN '30-60min'
            ELSE '60+min'
        END AS bucket_label,
        CASE
            WHEN total_duration_ms < 300000  THEN 0
            WHEN total_duration_ms < 900000  THEN 300000
            WHEN total_duration_ms < 1800000 THEN 900000
            WHEN total_duration_ms < 3600000 THEN 1800000
            ELSE 3600000
        END::bigint AS bucket_min_ms,
        CASE
            WHEN total_duration_ms < 300000  THEN 300000
            WHEN total_duration_ms < 900000  THEN 900000
            WHEN total_duration_ms < 1800000 THEN 1800000
            WHEN total_duration_ms < 3600000 THEN 3600000
            ELSE NULL
        END::bigint AS bucket_max_ms,
        COUNT(*) AS visit_count
    FROM visit_sessions
    WHERE store_id = $1
      AND entered_at_ms >= $3 AND entered_at_ms < $4
      AND is_employee = FALSE
      AND total_duration_ms IS NOT NULL
    GROUP BY 1, 2, 3
) d
ON CONFLICT (store_id, date, bucket_label) DO UPDATE SET
    bucket_min_ms = EXCLUDED.bucket_min_ms,
    bucket_max_ms = EXCLUDED.bucket_max_ms,
    visit_count   = EXCLUDED.visit_count
"""


async def run(conn, ctx: RunContext) -> None:
    agg = await conn.fetchrow(_VISIT_AGG, ctx.store_id, ctx.shift_start_ms, ctx.shift_end_ms)
    peak, peak_at = await occupancy.store_peak(conn, ctx.store_id, ctx.shift_start_ms, ctx.shift_end_ms)
    dead_count, dead_total = await occupancy.dead_periods(
        conn, ctx.store_id, ctx.shift_start_ms, ctx.shift_end_ms,
        ctx.dead_threshold, ctx.dead_duration_ms,
    )

    await conn.execute(
        _DAILY_STORE_UPSERT,
        ctx.store_id, ctx.shift_date,
        int(agg["total_visits"] or 0),
        int(agg["unique_visitors"] or 0),
        agg["avg_visit_duration_ms"],
        agg["median_visit_duration_ms"],
        peak, peak_at, dead_count, dead_total,
    )
    await conn.execute(
        _DIST_UPSERT, ctx.store_id, ctx.shift_date, ctx.shift_start_ms, ctx.shift_end_ms,
    )
