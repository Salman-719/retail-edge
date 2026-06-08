"""daily_zone_summary. Source: zone_transition_log (customers), with
max_concurrent from raw global_tracking_history and alert_trigger_count from
alerts JOIN alert_rule_zones. One pure-SQL upsert."""
from __future__ import annotations

from app.context import RunContext

_UPSERT = """
WITH ztl AS (
    SELECT zone_id,
        COUNT(DISTINCT global_id)                               AS unique_visitors,
        COUNT(*)                                                AS total_transitions,
        AVG(dwell_ms)::bigint                                   AS avg_dwell_ms,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dwell_ms)::bigint AS median_dwell_ms,
        COUNT(*) FILTER (WHERE dwell_ms < $4)                   AS passthrough_count,
        COUNT(*) FILTER (WHERE dwell_ms >= $4)                  AS engagement_count
    FROM zone_transition_log
    WHERE store_id = $1
      AND entered_at_ms >= $2 AND entered_at_ms < $3
      AND is_employee = FALSE
      AND zone_id IS NOT NULL
    GROUP BY zone_id
),
maxc AS (
    SELECT zone_id, MAX(occ) AS max_concurrent FROM (
        SELECT zone_id, (timestamp_ms / 900000) * 900000 AS b,
               COUNT(DISTINCT global_id) AS occ
        FROM global_tracking_history
        WHERE store_id = $1 AND timestamp_ms >= $2 AND timestamp_ms < $3
          AND zone_id IS NOT NULL
        GROUP BY zone_id, b
    ) t GROUP BY zone_id
),
alrt AS (
    SELECT arz.zone_id, COUNT(*) AS alert_trigger_count
    FROM alerts a
    JOIN alert_rule_zones arz ON arz.alert_rule_id = a.alert_rule_id
    WHERE a.store_id = $1
      AND a.is_followup = FALSE
      AND a.created_at >= to_timestamp($2 / 1000.0)
      AND a.created_at <  to_timestamp($3 / 1000.0)
    GROUP BY arz.zone_id
)
INSERT INTO analytics.daily_zone_summary (
    store_id, zone_id, date, unique_visitors, total_transitions,
    avg_dwell_ms, median_dwell_ms, max_concurrent,
    passthrough_count, engagement_count, alert_trigger_count
)
SELECT $1, ztl.zone_id, $5, ztl.unique_visitors, ztl.total_transitions,
       ztl.avg_dwell_ms, ztl.median_dwell_ms, COALESCE(maxc.max_concurrent, 0),
       ztl.passthrough_count, ztl.engagement_count, COALESCE(alrt.alert_trigger_count, 0)
FROM ztl
LEFT JOIN maxc ON maxc.zone_id = ztl.zone_id
LEFT JOIN alrt ON alrt.zone_id = ztl.zone_id
ON CONFLICT (store_id, zone_id, date) DO UPDATE SET
    unique_visitors     = EXCLUDED.unique_visitors,
    total_transitions   = EXCLUDED.total_transitions,
    avg_dwell_ms        = EXCLUDED.avg_dwell_ms,
    median_dwell_ms     = EXCLUDED.median_dwell_ms,
    max_concurrent      = EXCLUDED.max_concurrent,
    passthrough_count   = EXCLUDED.passthrough_count,
    engagement_count    = EXCLUDED.engagement_count,
    alert_trigger_count = EXCLUDED.alert_trigger_count
"""


async def run(conn, ctx: RunContext) -> None:
    await conn.execute(
        _UPSERT,
        ctx.store_id, ctx.shift_start_ms, ctx.shift_end_ms,
        ctx.passthrough_ms, ctx.shift_date,
    )
