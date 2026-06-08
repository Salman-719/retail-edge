"""daily_employee_summary. One row per employee with a shift_instance on the
shift date.

LIMITATION (same root cause as IEP4 staff_absence_employee): there is no
employee_id <-> global_id link (Employee ReID flow not implemented), so
zone_transition_log rows with is_employee = TRUE cannot be attributed to a
specific employee. Therefore only scheduled_duration_ms (from shift_instances)
is computable here; present_duration_ms / presence_ratio /
zone_punctuality_delay_ms / unassigned_zone_time_ms are written NULL until the
ReID linkage exists. Documented deviation from the spec's per-employee presence
calculations.
"""
from __future__ import annotations

from app.context import RunContext

_UPSERT = """
INSERT INTO analytics.daily_employee_summary (
    store_id, employee_id, date, scheduled_duration_ms,
    present_duration_ms, presence_ratio,
    zone_punctuality_delay_ms, unassigned_zone_time_ms
)
SELECT $1, si.employee_id, $2,
       SUM((EXTRACT(EPOCH FROM (si.scheduled_end - si.scheduled_start)) * 1000))::bigint,
       NULL::bigint, NULL::float, NULL::bigint, NULL::bigint
FROM shift_instances si
JOIN employees e ON e.id = si.employee_id
WHERE e.store_id = $1
  AND (si.scheduled_start)::date = $2
GROUP BY si.employee_id
ON CONFLICT (store_id, employee_id, date) DO UPDATE SET
    scheduled_duration_ms = EXCLUDED.scheduled_duration_ms
"""


async def run(conn, ctx: RunContext) -> None:
    await conn.execute(_UPSERT, ctx.store_id, ctx.shift_date)
