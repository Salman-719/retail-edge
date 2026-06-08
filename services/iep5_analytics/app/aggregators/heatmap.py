"""heatmap_hourly (from raw global_tracking_history) + heatmap_daily (sum of
hourly). Grid is world-coordinate space; cell identified by integer (grid_x,
grid_y) from floor-plan origin and cell size."""
from __future__ import annotations

from app.context import RunContext

_HOURLY_UPSERT = """
INSERT INTO analytics.heatmap_hourly (
    store_id, version_id, hour_bucket, grid_x, grid_y, hit_count
)
SELECT $1, $2,
       (timestamp_ms / 3600000) * 3600000          AS hour_bucket,
       floor((floor_x - $3) / $4)::int             AS grid_x,
       floor((floor_y - $5) / $4)::int             AS grid_y,
       COUNT(*)                                     AS hit_count
FROM global_tracking_history
WHERE store_id = $1
  AND timestamp_ms >= $6 AND timestamp_ms < $7
  AND floor_x IS NOT NULL AND floor_y IS NOT NULL
GROUP BY hour_bucket, grid_x, grid_y
ON CONFLICT (store_id, hour_bucket, grid_x, grid_y) DO UPDATE SET
    hit_count  = EXCLUDED.hit_count,
    version_id = EXCLUDED.version_id
"""

_DAILY_UPSERT = """
INSERT INTO analytics.heatmap_daily (
    store_id, version_id, date, grid_x, grid_y, hit_count
)
SELECT $1, $2, $3, grid_x, grid_y, SUM(hit_count)
FROM analytics.heatmap_hourly
WHERE store_id = $1 AND hour_bucket >= $4 AND hour_bucket < $5
GROUP BY grid_x, grid_y
ON CONFLICT (store_id, date, grid_x, grid_y) DO UPDATE SET
    hit_count  = EXCLUDED.hit_count,
    version_id = EXCLUDED.version_id
"""


async def run(conn, ctx: RunContext) -> None:
    await conn.execute(
        _HOURLY_UPSERT,
        ctx.store_id, ctx.version_id,
        ctx.origin_x, ctx.cell_size_m, ctx.origin_y,
        ctx.shift_start_ms, ctx.shift_end_ms,
    )
    await conn.execute(
        _DAILY_UPSERT,
        ctx.store_id, ctx.version_id, ctx.shift_date,
        ctx.shift_start_ms, ctx.shift_end_ms,
    )
