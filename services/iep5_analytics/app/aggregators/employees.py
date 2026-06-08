"""daily_employee_summary. One row per employee with a shift_instance on the
shift date.

present_duration_ms: sum of closed visit_sessions durations where the session's
global_id is linked to this employee via global_identities.employee_id. Only
counts sessions that started on the shift date (by entered_at_ms). Employees
without a punch-in link will show NULL (no global_id linked yet).

zone_punctuality_delay_ms / unassigned_zone_time_ms: deferred (NULL).
"""
from __future__ import annotations

from app.context import RunContext

_UPSERT = """
WITH shifts AS (
    SELECT si.employee_id,
           SUM((EXTRACT(EPOCH FROM (si.scheduled_end - si.scheduled_start)) * 1000))::bigint
               AS scheduled_duration_ms
    FROM shift_instances si
    JOIN employees e ON e.id = si.employee_id
    WHERE e.store_id = $1
      AND (si.scheduled_start)::date = $2
    GROUP BY si.employee_id
),
presence AS (
    SELECT gi.employee_id,
           SUM(vs.exited_at_ms - vs.entered_at_ms)::bigint AS present_duration_ms
    FROM visit_sessions vs
    JOIN global_identities gi ON gi.global_id = vs.global_id
    WHERE vs.store_id = $1
      AND gi.employee_id IS NOT NULL
      AND vs.exited_at_ms IS NOT NULL
      AND to_timestamp(vs.entered_at_ms / 1000.0) AT TIME ZONE 'UTC' >= $2::date::timestamptz
      AND to_timestamp(vs.entered_at_ms / 1000.0) AT TIME ZONE 'UTC' <  ($2::date + 1)::timestamptz
    GROUP BY gi.employee_id
)
INSERT INTO analytics.daily_employee_summary (
    store_id, employee_id, date, scheduled_duration_ms,
    present_duration_ms, presence_ratio,
    zone_punctuality_delay_ms, unassigned_zone_time_ms
)
SELECT $1,
       s.employee_id,
       $2,
       s.scheduled_duration_ms,
       p.present_duration_ms,
       CASE
           WHEN s.scheduled_duration_ms > 0 AND p.present_duration_ms IS NOT NULL
           THEN LEAST(p.present_duration_ms::float / s.scheduled_duration_ms, 1.0)
           ELSE NULL
       END,
       NULL::bigint,
       NULL::bigint
FROM shifts s
LEFT JOIN presence p ON p.employee_id = s.employee_id
ON CONFLICT (store_id, employee_id, date) DO UPDATE SET
    scheduled_duration_ms = EXCLUDED.scheduled_duration_ms,
    present_duration_ms   = EXCLUDED.present_duration_ms,
    presence_ratio        = EXCLUDED.presence_ratio
"""


async def run(conn, ctx: RunContext) -> None:
    await conn.execute(_UPSERT, ctx.store_id, ctx.shift_date)
