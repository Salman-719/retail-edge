"""SQL constants for IEP4. All SQL lives here; postgres.py binds and runs them.

batch_number is the window_start_ms of a 60s batch (SPEC-002), so it is an
ordered epoch-ms integer. timestamp_ms on global_tracking_history is the 5s
bucket boundary.
"""

# ── Cursor / guards ──────────────────────────────────────────────────────────

MAX_BATCH = """
SELECT max(batch_number) AS m
FROM global_tracking_history
WHERE store_id = $1
"""

HAS_ACTIVE_VERSION = """
SELECT 1 FROM store_config_versions
WHERE store_id = $1 AND status = 'active'
LIMIT 1
"""

ACTIVE_VERSION_ID = """
SELECT id FROM store_config_versions
WHERE store_id = $1 AND status = 'active'
LIMIT 1
"""

# ── Delta read ───────────────────────────────────────────────────────────────
# JOIN global_identities for is_employee, used when inserting new aps rows.

GET_DELTA = """
SELECT gth.global_id, gth.zone_id, gth.timestamp_ms, gth.batch_number,
       gth.floor_x, gth.floor_y, gth.source_camera, gi.is_employee, gi.employee_id
FROM global_tracking_history gth
JOIN global_identities gi ON gi.global_id = gth.global_id
WHERE gth.store_id = $1
  AND gth.batch_number > $2
  AND gth.batch_number <= $3
ORDER BY gth.global_id, gth.timestamp_ms ASC
"""

# ── active_person_state ──────────────────────────────────────────────────────

UPSERT_ACTIVE_PERSON_STATE = """
INSERT INTO active_person_state (
    global_id, store_id, current_zone_id,
    entered_current_zone_at, last_seen_at,
    last_batch_number, is_employee, employee_id, updated_at
)
SELECT * FROM unnest(
    $1::uuid[], $2::uuid[], $3::uuid[],
    $4::bigint[], $5::bigint[],
    $6::bigint[], $7::bool[], $8::uuid[], $9::timestamptz[]
)
ON CONFLICT (global_id, store_id) DO UPDATE SET
    current_zone_id         = EXCLUDED.current_zone_id,
    entered_current_zone_at = CASE
        WHEN active_person_state.current_zone_id IS DISTINCT FROM EXCLUDED.current_zone_id
        THEN EXCLUDED.entered_current_zone_at
        ELSE active_person_state.entered_current_zone_at
    END,
    last_seen_at      = EXCLUDED.last_seen_at,
    last_batch_number = EXCLUDED.last_batch_number,
    is_employee       = EXCLUDED.is_employee,
    employee_id       = COALESCE(EXCLUDED.employee_id, active_person_state.employee_id),
    updated_at        = EXCLUDED.updated_at
"""

LOAD_ACTIVE_PERSON_STATE = """
SELECT global_id, current_zone_id, entered_current_zone_at,
       last_seen_at, last_batch_number, is_employee, employee_id
FROM active_person_state
WHERE store_id = $1
"""

DELETE_ACTIVE_PERSON_STATE = """
DELETE FROM active_person_state
WHERE store_id = $1 AND global_id = ANY($2::uuid[])
"""

# ── Zone transitions ─────────────────────────────────────────────────────────

INSERT_ZONE_TRANSITIONS = """
INSERT INTO zone_transition_log (
    global_id, store_id, zone_id,
    entered_at_ms, exited_at_ms, is_employee,
    entry_batch, exit_batch
)
SELECT * FROM unnest(
    $1::uuid[], $2::uuid[], $3::uuid[],
    $4::bigint[], $5::bigint[], $6::bool[],
    $7::bigint[], $8::bigint[]
)
"""

# ── Visit sessions ───────────────────────────────────────────────────────────

OPEN_VISIT = """
INSERT INTO visit_sessions (global_id, store_id, entered_at_ms, is_employee, version_id)
VALUES ($1, $2, $3, $4, $5)
"""

# Close the open visit for a global_id, deriving zones_visited and entry/exit
# zones from zone_transition_log rows recorded since the visit opened.
CLOSE_VISIT = """
WITH open_visit AS (
    SELECT id, entered_at_ms
    FROM visit_sessions
    WHERE store_id = $1 AND global_id = $2 AND exited_at_ms IS NULL
    ORDER BY entered_at_ms DESC
    LIMIT 1
),
transitions AS (
    SELECT ztl.zone_id, ztl.entered_at_ms
    FROM zone_transition_log ztl, open_visit
    WHERE ztl.store_id = $1
      AND ztl.global_id = $2
      AND ztl.entered_at_ms >= open_visit.entered_at_ms
),
agg AS (
    SELECT
        COUNT(*) AS n,
        (ARRAY_AGG(zone_id ORDER BY entered_at_ms ASC))[1] AS entry_zone,
        (ARRAY_AGG(zone_id ORDER BY entered_at_ms DESC))[1] AS exit_zone
    FROM transitions
)
UPDATE visit_sessions vs
SET exited_at_ms  = GREATEST($3, open_visit.entered_at_ms + 1),
    zones_visited = COALESCE((SELECT n FROM agg), 0),
    entry_zone_id = (SELECT entry_zone FROM agg),
    exit_zone_id  = (SELECT exit_zone FROM agg)
FROM open_visit
WHERE vs.id = open_visit.id
"""

# ── global_identities lifecycle ──────────────────────────────────────────────

GET_GLOBAL_STATES = """
SELECT global_id, state
FROM global_identities
WHERE global_id = ANY($1::uuid[])
"""

# ── Alert rules / zones / state ──────────────────────────────────────────────

LOAD_ACTIVE_RULES = """
SELECT id, type, name, threshold_minutes, cooldown_minutes,
       followup_interval_minutes, people_threshold, min_employees,
       employee_id, only_during_shift
FROM alert_rules
WHERE store_id = $1 AND is_active = TRUE
"""

LOAD_RULE_ZONES = """
SELECT alert_rule_id, zone_id
FROM alert_rule_zones
WHERE alert_rule_id = ANY($1::uuid[])
"""

LOAD_ALERT_STATES = """
SELECT alert_rule_id, status, condition_first_met_at, fired_at,
       condition_cleared_at, cooldown_until, last_evaluated_at, last_followup_at
FROM alert_state
WHERE alert_rule_id = ANY($1::uuid[])
"""

UPSERT_ALERT_STATE = """
INSERT INTO alert_state (
    alert_rule_id, status, condition_first_met_at, fired_at,
    condition_cleared_at, cooldown_until, last_evaluated_at, last_followup_at,
    updated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
ON CONFLICT (alert_rule_id) DO UPDATE SET
    status                 = EXCLUDED.status,
    condition_first_met_at = EXCLUDED.condition_first_met_at,
    fired_at               = EXCLUDED.fired_at,
    condition_cleared_at   = EXCLUDED.condition_cleared_at,
    cooldown_until         = EXCLUDED.cooldown_until,
    last_evaluated_at      = EXCLUDED.last_evaluated_at,
    last_followup_at       = EXCLUDED.last_followup_at,
    updated_at             = now()
"""

# ── Evaluation counts ────────────────────────────────────────────────────────

COUNT_QUEUE_BUILDUP = """
SELECT COUNT(*) AS n
FROM active_person_state
WHERE store_id = $1
  AND current_zone_id = ANY($2::uuid[])
  AND (last_seen_at - entered_current_zone_at) >= $3
  AND is_employee = FALSE
"""

COUNT_STAFF_IN_ZONES = """
SELECT COUNT(*) AS n
FROM active_person_state
WHERE store_id = $1
  AND current_zone_id = ANY($2::uuid[])
  AND is_employee = TRUE
"""

ACTIVE_SHIFT_FOR_EMPLOYEE = """
SELECT 1 FROM shift_instances
WHERE employee_id = $1
  AND status = 'active'
  AND scheduled_start <= now()
  AND scheduled_end   >= now()
LIMIT 1
"""

LATEST_EMPLOYEE_PRESENCE = """
SELECT MAX(aps.last_seen_at) AS last_seen_at
FROM active_person_state aps
WHERE aps.store_id = $1
  AND aps.is_employee = TRUE
"""

# Presence of a specific linked employee (uses employee_id set by the punch resolver).
LATEST_PRESENCE_FOR_EMPLOYEE = """
SELECT MAX(aps.last_seen_at) AS last_seen_at
FROM active_person_state aps
WHERE aps.store_id = $1
  AND aps.employee_id = $2
"""

# ── Alerts ───────────────────────────────────────────────────────────────────

INSERT_ALERT = """
INSERT INTO alerts (store_id, type, zone_id, details, alert_rule_id, is_followup)
VALUES ($1, $2, $3, $4::jsonb, $5, $6)
"""

RESOLVE_ALERTS_FOR_RULE = """
UPDATE alerts
SET resolved_at = now(), resolution = 'auto_detected'
WHERE alert_rule_id = $1 AND resolved_at IS NULL
"""

ZONE_NAMES = """
SELECT id, name FROM zones WHERE id = ANY($1::uuid[])
"""

# ── Email recipients ─────────────────────────────────────────────────────────

RECIPIENTS = """
SELECT u.email FROM users u
JOIN store_members sm ON sm.user_id = u.id
JOIN store_member_permissions smp ON smp.store_member_id = sm.id
WHERE sm.store_id = $1
  AND smp.permission = 'receive_notifications'
  AND smp.granted = TRUE
UNION
SELECT u.email FROM users u
JOIN stores s ON s.created_by = u.id
WHERE s.id = $1
"""
