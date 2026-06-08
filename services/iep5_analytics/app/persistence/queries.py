"""Read/preflight SQL for IEP5. Aggregator WRITE sql lives in each aggregator
module (cohesive per output table)."""

# ── Preflight ────────────────────────────────────────────────────────────────

COUNT_OPEN_VISITS = """
SELECT COUNT(*) FROM visit_sessions
WHERE store_id = $1 AND exited_at_ms IS NULL
"""

COUNT_ACTIVE_PERSON_STATE = """
SELECT COUNT(*) FROM active_person_state WHERE store_id = $1
"""

COUNT_GTH_IN_WINDOW = """
SELECT COUNT(*) FROM global_tracking_history
WHERE store_id = $1 AND timestamp_ms >= $2 AND timestamp_ms < $3
"""

COUNT_EXISTING_DAILY = """
SELECT COUNT(*) FROM analytics.daily_store_summary
WHERE store_id = $1 AND date = $2
"""

# ── Context ──────────────────────────────────────────────────────────────────

SHIFT_BOUNDS = """
SELECT MIN(timestamp_ms) AS shift_start_ms,
       MAX(timestamp_ms) AS shift_end_ms
FROM global_tracking_history
WHERE store_id = $1 AND timestamp_ms >= $2 AND timestamp_ms < $3
"""

# Active version + floor-plan origin (for the heatmap grid). Origin defaults to
# 0,0 when no floor plan / scale is set.
ACTIVE_VERSION_ORIGIN = """
SELECT scv.id AS version_id,
       COALESCE(fp.origin_x, 0) AS origin_x,
       COALESCE(fp.origin_y, 0) AS origin_y
FROM store_config_versions scv
LEFT JOIN floor_plans fp
       ON fp.version_id = scv.id AND fp.store_id = scv.store_id
WHERE scv.store_id = $1 AND scv.status = 'active'
LIMIT 1
"""
