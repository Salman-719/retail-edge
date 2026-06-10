"""Weekly + monthly accumulating rollups. Run every shift end. Each sums from
the corresponding daily analytics table over the week/month range up to the
shift date (never from raw data). is_complete is TRUE only on the last day of
the ISO week / calendar month."""
from __future__ import annotations

from app.context import RunContext

# ── Weekly ───────────────────────────────────────────────────────────────────

_WEEKLY_STORE = """
INSERT INTO analytics.weekly_store_summary (
    store_id, iso_year, iso_week, week_start_date,
    total_visits, unique_visitors, avg_visit_duration_ms,
    median_visit_duration_ms, peak_occupancy, dead_period_count,
    is_complete, updated_at
)
SELECT $1, $2, $3, $4,
    SUM(total_visits), SUM(unique_visitors), AVG(avg_visit_duration_ms)::bigint,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_visit_duration_ms)::bigint,
    MAX(peak_occupancy), SUM(dead_period_count), $5, now()
FROM analytics.daily_store_summary
WHERE store_id = $1 AND date >= $4 AND date <= $6
ON CONFLICT (store_id, iso_year, iso_week) DO UPDATE SET
    total_visits             = EXCLUDED.total_visits,
    unique_visitors          = EXCLUDED.unique_visitors,
    avg_visit_duration_ms    = EXCLUDED.avg_visit_duration_ms,
    median_visit_duration_ms = EXCLUDED.median_visit_duration_ms,
    peak_occupancy           = EXCLUDED.peak_occupancy,
    dead_period_count        = EXCLUDED.dead_period_count,
    is_complete              = EXCLUDED.is_complete,
    updated_at               = EXCLUDED.updated_at
"""

_WEEKLY_ZONE = """
INSERT INTO analytics.weekly_zone_summary (
    store_id, zone_id, iso_year, iso_week,
    unique_visitors, avg_dwell_ms, median_dwell_ms,
    passthrough_count, engagement_count, is_complete, updated_at
)
SELECT $1, zone_id, $2, $3,
    SUM(unique_visitors), AVG(avg_dwell_ms)::bigint,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_dwell_ms)::bigint,
    SUM(passthrough_count), SUM(engagement_count), $4, now()
FROM analytics.daily_zone_summary
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY zone_id
ON CONFLICT (store_id, zone_id, iso_year, iso_week) DO UPDATE SET
    unique_visitors   = EXCLUDED.unique_visitors,
    avg_dwell_ms      = EXCLUDED.avg_dwell_ms,
    median_dwell_ms   = EXCLUDED.median_dwell_ms,
    passthrough_count = EXCLUDED.passthrough_count,
    engagement_count  = EXCLUDED.engagement_count,
    is_complete       = EXCLUDED.is_complete,
    updated_at        = EXCLUDED.updated_at
"""

_WEEKLY_EMPLOYEE = """
INSERT INTO analytics.weekly_employee_summary (
    store_id, employee_id, iso_year, iso_week,
    scheduled_duration_ms, present_duration_ms,
    avg_presence_ratio, avg_punctuality_delay_ms, is_complete, updated_at
)
SELECT $1, employee_id, $2, $3,
    SUM(scheduled_duration_ms), SUM(present_duration_ms),
    AVG(presence_ratio), AVG(zone_punctuality_delay_ms)::bigint, $4, now()
FROM analytics.daily_employee_summary
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY employee_id
ON CONFLICT (store_id, employee_id, iso_year, iso_week) DO UPDATE SET
    scheduled_duration_ms    = EXCLUDED.scheduled_duration_ms,
    present_duration_ms      = EXCLUDED.present_duration_ms,
    avg_presence_ratio       = EXCLUDED.avg_presence_ratio,
    avg_punctuality_delay_ms = EXCLUDED.avg_punctuality_delay_ms,
    is_complete              = EXCLUDED.is_complete,
    updated_at               = EXCLUDED.updated_at
"""

_HEATMAP_WEEKLY = """
INSERT INTO analytics.heatmap_weekly (
    store_id, iso_year, iso_week, grid_x, grid_y, hit_count, is_complete, updated_at
)
SELECT $1, $2, $3, grid_x, grid_y, SUM(hit_count), $4, now()
FROM analytics.heatmap_daily
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY grid_x, grid_y
ON CONFLICT (store_id, iso_year, iso_week, grid_x, grid_y) DO UPDATE SET
    hit_count   = EXCLUDED.hit_count,
    is_complete = EXCLUDED.is_complete,
    updated_at  = EXCLUDED.updated_at
"""

# ── Monthly ──────────────────────────────────────────────────────────────────

_MONTHLY_STORE = """
INSERT INTO analytics.monthly_store_summary (
    store_id, year, month, month_start_date,
    total_visits, unique_visitors, avg_visit_duration_ms,
    median_visit_duration_ms, peak_occupancy, dead_period_count,
    is_complete, updated_at
)
SELECT $1, $2, $3, $4,
    SUM(total_visits), SUM(unique_visitors), AVG(avg_visit_duration_ms)::bigint,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_visit_duration_ms)::bigint,
    MAX(peak_occupancy), SUM(dead_period_count), $5, now()
FROM analytics.daily_store_summary
WHERE store_id = $1 AND date >= $4 AND date <= $6
ON CONFLICT (store_id, year, month) DO UPDATE SET
    total_visits             = EXCLUDED.total_visits,
    unique_visitors          = EXCLUDED.unique_visitors,
    avg_visit_duration_ms    = EXCLUDED.avg_visit_duration_ms,
    median_visit_duration_ms = EXCLUDED.median_visit_duration_ms,
    peak_occupancy           = EXCLUDED.peak_occupancy,
    dead_period_count        = EXCLUDED.dead_period_count,
    is_complete              = EXCLUDED.is_complete,
    updated_at               = EXCLUDED.updated_at
"""

_MONTHLY_ZONE = """
INSERT INTO analytics.monthly_zone_summary (
    store_id, zone_id, year, month,
    unique_visitors, avg_dwell_ms, median_dwell_ms,
    passthrough_count, engagement_count, is_complete, updated_at
)
SELECT $1, zone_id, $2, $3,
    SUM(unique_visitors), AVG(avg_dwell_ms)::bigint,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY median_dwell_ms)::bigint,
    SUM(passthrough_count), SUM(engagement_count), $4, now()
FROM analytics.daily_zone_summary
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY zone_id
ON CONFLICT (store_id, zone_id, year, month) DO UPDATE SET
    unique_visitors   = EXCLUDED.unique_visitors,
    avg_dwell_ms      = EXCLUDED.avg_dwell_ms,
    median_dwell_ms   = EXCLUDED.median_dwell_ms,
    passthrough_count = EXCLUDED.passthrough_count,
    engagement_count  = EXCLUDED.engagement_count,
    is_complete       = EXCLUDED.is_complete,
    updated_at        = EXCLUDED.updated_at
"""

_MONTHLY_EMPLOYEE = """
INSERT INTO analytics.monthly_employee_summary (
    store_id, employee_id, year, month,
    scheduled_duration_ms, present_duration_ms,
    avg_presence_ratio, avg_punctuality_delay_ms, is_complete, updated_at
)
SELECT $1, employee_id, $2, $3,
    SUM(scheduled_duration_ms), SUM(present_duration_ms),
    AVG(presence_ratio), AVG(zone_punctuality_delay_ms)::bigint, $4, now()
FROM analytics.daily_employee_summary
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY employee_id
ON CONFLICT (store_id, employee_id, year, month) DO UPDATE SET
    scheduled_duration_ms    = EXCLUDED.scheduled_duration_ms,
    present_duration_ms      = EXCLUDED.present_duration_ms,
    avg_presence_ratio       = EXCLUDED.avg_presence_ratio,
    avg_punctuality_delay_ms = EXCLUDED.avg_punctuality_delay_ms,
    is_complete              = EXCLUDED.is_complete,
    updated_at               = EXCLUDED.updated_at
"""

_HEATMAP_MONTHLY = """
INSERT INTO analytics.heatmap_monthly (
    store_id, year, month, grid_x, grid_y, hit_count, is_complete, updated_at
)
SELECT $1, $2, $3, grid_x, grid_y, SUM(hit_count), $4, now()
FROM analytics.heatmap_daily
WHERE store_id = $1 AND date >= $5 AND date <= $6
GROUP BY grid_x, grid_y
ON CONFLICT (store_id, year, month, grid_x, grid_y) DO UPDATE SET
    hit_count   = EXCLUDED.hit_count,
    is_complete = EXCLUDED.is_complete,
    updated_at  = EXCLUDED.updated_at
"""


async def run(conn, ctx: RunContext) -> None:
    # Weekly (store / zone / employee / heatmap)
    await conn.execute(_WEEKLY_STORE, ctx.store_id, ctx.iso_year, ctx.iso_week,
                       ctx.week_start_date, ctx.is_week_complete, ctx.shift_date)
    await conn.execute(_WEEKLY_ZONE, ctx.store_id, ctx.iso_year, ctx.iso_week,
                       ctx.is_week_complete, ctx.week_start_date, ctx.shift_date)
    await conn.execute(_WEEKLY_EMPLOYEE, ctx.store_id, ctx.iso_year, ctx.iso_week,
                       ctx.is_week_complete, ctx.week_start_date, ctx.shift_date)
    await conn.execute(_HEATMAP_WEEKLY, ctx.store_id, ctx.iso_year, ctx.iso_week,
                       ctx.is_week_complete, ctx.week_start_date, ctx.shift_date)
    # Monthly (store / zone / employee / heatmap)
    await conn.execute(_MONTHLY_STORE, ctx.store_id, ctx.year, ctx.month,
                       ctx.month_start_date, ctx.is_month_complete, ctx.shift_date)
    await conn.execute(_MONTHLY_ZONE, ctx.store_id, ctx.year, ctx.month,
                       ctx.is_month_complete, ctx.month_start_date, ctx.shift_date)
    await conn.execute(_MONTHLY_EMPLOYEE, ctx.store_id, ctx.year, ctx.month,
                       ctx.is_month_complete, ctx.month_start_date, ctx.shift_date)
    await conn.execute(_HEATMAP_MONTHLY, ctx.store_id, ctx.year, ctx.month,
                       ctx.is_month_complete, ctx.month_start_date, ctx.shift_date)
