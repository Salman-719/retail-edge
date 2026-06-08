"""Occupancy helpers — peak occupancy, dead periods, and per-zone max concurrent.

Computed from raw global_tracking_history in 15-minute buckets. SPEC-001's
zone_occupancy_15min continuous aggregate stores only total_observations (not
unique_visitors, which TimescaleDB caggs cannot compute), so uniques are derived
from raw here. Reading raw also means there is no continuous-aggregate refresh
lag to fall back around — the latest data is always present.
"""
from __future__ import annotations

# Peak 15-min bucket by distinct people present.
_PEAK = """
WITH buckets AS (
    SELECT (timestamp_ms / 900000) * 900000 AS bucket_ms,
           COUNT(DISTINCT global_id)        AS occ
    FROM global_tracking_history
    WHERE store_id = $1 AND timestamp_ms >= $2 AND timestamp_ms < $3
    GROUP BY 1
)
SELECT bucket_ms, occ FROM buckets ORDER BY occ DESC, bucket_ms ASC LIMIT 1
"""

# Dead periods: runs of consecutive 15-min buckets (gaps treated as 0 people)
# strictly below the threshold, lasting at least dead_duration_ms.
_DEAD = """
WITH series AS (
    SELECT generate_series(
        ((($2)::bigint / 900000) * 900000),
        ((($3)::bigint / 900000) * 900000),
        900000
    ) AS bucket_ms
),
occ AS (
    SELECT (timestamp_ms / 900000) * 900000 AS bucket_ms,
           COUNT(DISTINCT global_id)        AS n
    FROM global_tracking_history
    WHERE store_id = $1 AND timestamp_ms >= $2 AND timestamp_ms < $3
    GROUP BY 1
),
filled AS (
    SELECT s.bucket_ms, COALESCE(o.n, 0) AS occ
    FROM series s LEFT JOIN occ o USING (bucket_ms)
),
flagged AS (
    SELECT bucket_ms,
           (occ < $4) AS dead,
           ROW_NUMBER() OVER (ORDER BY bucket_ms)
             - ROW_NUMBER() OVER (PARTITION BY (occ < $4) ORDER BY bucket_ms) AS grp
    FROM filled
),
islands AS (
    SELECT COUNT(*) * 900000 AS duration_ms
    FROM flagged WHERE dead GROUP BY grp
)
SELECT COUNT(*) FILTER (WHERE duration_ms >= $5)                       AS dead_count,
       COALESCE(SUM(duration_ms) FILTER (WHERE duration_ms >= $5), 0)  AS dead_total_ms
FROM islands
"""

async def store_peak(conn, store_id, start_ms, end_ms) -> tuple[int, int | None]:
    row = await conn.fetchrow(_PEAK, store_id, start_ms, end_ms)
    if row is None or row["occ"] is None:
        return 0, None
    return int(row["occ"]), int(row["bucket_ms"])


async def dead_periods(conn, store_id, start_ms, end_ms, threshold, duration_ms) -> tuple[int, int]:
    row = await conn.fetchrow(_DEAD, store_id, start_ms, end_ms, threshold, duration_ms)
    return int(row["dead_count"] or 0), int(row["dead_total_ms"] or 0)


async def zone_max_concurrent(conn, store_id, start_ms, end_ms) -> dict[uuid.UUID, int]:
    rows = await conn.fetch(_ZONE_MAX_CONCURRENT, store_id, start_ms, end_ms)
    return {r["zone_id"]: int(r["max_concurrent"]) for r in rows}
