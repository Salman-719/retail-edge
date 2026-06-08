"""zone_sequence_matrix — zone-to-zone transition probabilities (customers).
Source: zone_transition_log ordered per person. Pure SQL (LEAD window)."""
from __future__ import annotations

from app.context import RunContext

_UPSERT = """
WITH ordered AS (
    SELECT global_id, zone_id, entered_at_ms,
           LEAD(zone_id) OVER (PARTITION BY global_id ORDER BY entered_at_ms) AS next_zone_id
    FROM zone_transition_log
    WHERE store_id = $1
      AND entered_at_ms >= $2 AND entered_at_ms < $3
      AND is_employee = FALSE
),
pairs AS (
    SELECT zone_id AS from_zone_id, next_zone_id AS to_zone_id, COUNT(*) AS cnt
    FROM ordered
    WHERE next_zone_id IS NOT NULL
    GROUP BY zone_id, next_zone_id
),
totals AS (
    SELECT from_zone_id, SUM(cnt) AS total FROM pairs GROUP BY from_zone_id
)
INSERT INTO analytics.zone_sequence_matrix (
    store_id, date, from_zone_id, to_zone_id, transition_count, probability
)
SELECT $1, $4, p.from_zone_id, p.to_zone_id, p.cnt, p.cnt::float / t.total
FROM pairs p JOIN totals t ON t.from_zone_id = p.from_zone_id
ON CONFLICT (store_id, date, from_zone_id, to_zone_id) DO UPDATE SET
    transition_count = EXCLUDED.transition_count,
    probability      = EXCLUDED.probability
"""


async def run(conn, ctx: RunContext) -> None:
    await conn.execute(_UPSERT, ctx.store_id, ctx.shift_start_ms, ctx.shift_end_ms, ctx.shift_date)
