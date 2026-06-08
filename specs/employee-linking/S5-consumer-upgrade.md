# S5 — Consumer Upgrade (IEP4 + IEP5 use the specific `employee_id`)

_Now that `global_identities.employee_id` is populated, replace the "any staff member"
fallbacks with real per-employee logic. Depends on S4 producing links._

## Read before implementing
- [iep4_alerts/app/persistence/queries.py](../../services/iep4_alerts/app/persistence/queries.py)
  — `LATEST_EMPLOYEE_PRESENCE` (L215), `GET_DELTA` (L31), `active_person_state`.
- [iep4_alerts/app/alerts/staff_employee.py](../../services/iep4_alerts/app/alerts/staff_employee.py)
  — `repo.latest_employee_presence()` usage.
- [iep4_alerts/app/persistence/postgres.py](../../services/iep4_alerts/app/persistence/postgres.py)
  — repo method wiring.
- [iep5_analytics/app/aggregators/employees.py](../../services/iep5_analytics/app/aggregators/employees.py)
  — the NULL-filled `daily_employee_summary` upsert.

## IEP4 — propagate `employee_id` into live state

`active_person_state.employee_id` (added in S1) must flow the same way `is_employee` already
does. Touch these in lockstep (read [state/person_state.py](../../services/iep4_alerts/app/state/person_state.py),
[models.py](../../services/iep4_alerts/app/models.py), [persistence/postgres.py](../../services/iep4_alerts/app/persistence/postgres.py)):

1. **`GET_DELTA`** (queries.py:31) — add `gi.employee_id` to the SELECT alongside `gi.is_employee`.
2. **`DeltaRow`** model — add `employee_id: uuid.UUID | None`.
3. **`PersonState`** model — add `employee_id: uuid.UUID | None`.
4. **`compute_states`** (person_state.py:61) — set `employee_id=last.employee_id` (same as
   `is_employee=last.is_employee`).
5. **`PersonStateManager.persist`** (person_state.py:80) — add `s.employee_id` to the row tuple.
6. **`UPSERT_ACTIVE_PERSON_STATE`** (queries.py:44) — add an `$N::uuid[]` array param + column +
   `DO UPDATE SET employee_id = EXCLUDED.employee_id`; update `upsert_active_person_state` binding
   in postgres.py.
7. **`LOAD_ACTIVE_PERSON_STATE`** (queries.py:68) — add `employee_id` to the SELECT and to the
   in-memory `PersonState` reconstruction.

Result: an active employee's `employee_id` lands in `active_person_state` on the next IEP4
batch after the punch link (and the S4 resolver also writes it immediately for the existing row).

## IEP4 — targeted staff-absence presence

### New query (replace `LATEST_EMPLOYEE_PRESENCE` usage for targeted rules)
```sql
-- Latest presence of ONE specific employee. MAX across any global_ids currently
-- linked to this employee (normally one, kept stable by IEP3 ReID recovery).
LATEST_PRESENCE_FOR_EMPLOYEE = """
SELECT MAX(aps.last_seen_at) AS last_seen_at
FROM active_person_state aps
WHERE aps.store_id = $1
  AND aps.employee_id = $2
"""
```
(Uses `active_person_state.employee_id` directly — populated by S4 + the IEP4 propagation
above. No join needed.)
- Add `repo.latest_presence_for_employee(store_id, employee_id)` in `postgres.py`.
- In `staff_employee.py::evaluate`, when `rule.employee_id is not None`, call the new method
  instead of `repo.latest_employee_presence()`. Update the docstring/`LIMITATION` note —
  the limitation is now resolved for linked employees. If `rule.employee_id is None`, keep
  the existing store-wide fallback.
- Presence reflects the linked identity, which IEP3 keeps stable across loss/re-acquisition;
  it only lapses if the employee fully exits the store (terminal `exited`) and returns as a
  new `global_id` before re-punching.

## IEP5 — real `daily_employee_summary`

Upgrade `employees.py` to fill `present_duration_ms` and `presence_ratio`. Keep
`zone_punctuality_delay_ms` and `unassigned_zone_time_ms` **NULL** — they require an
employee→assigned-zone model that does not exist (no such table). Document this remaining
partial.

### Presence from `visit_sessions` joined to the link
```sql
INSERT INTO analytics.daily_employee_summary (
    store_id, employee_id, date, scheduled_duration_ms,
    present_duration_ms, presence_ratio,
    zone_punctuality_delay_ms, unassigned_zone_time_ms
)
WITH sched AS (
    SELECT si.employee_id,
           SUM(EXTRACT(EPOCH FROM (si.scheduled_end - si.scheduled_start)) * 1000)::bigint
               AS scheduled_ms
    FROM shift_instances si
    JOIN employees e ON e.id = si.employee_id
    WHERE e.store_id = $1 AND (si.scheduled_start)::date = $2
    GROUP BY si.employee_id
),
present AS (
    SELECT gi.employee_id,
           SUM(COALESCE(vs.total_duration_ms, 0))::bigint AS present_ms
    FROM visit_sessions vs
    JOIN global_identities gi ON gi.global_id = vs.global_id
    WHERE vs.store_id = $1
      AND gi.employee_id IS NOT NULL
      AND to_timestamp(vs.entered_at_ms / 1000.0)::date = $2
    GROUP BY gi.employee_id
)
SELECT $1, sched.employee_id, $2,
       sched.scheduled_ms,
       present.present_ms,
       CASE WHEN sched.scheduled_ms > 0 AND present.present_ms IS NOT NULL
            THEN LEAST(1.0, present.present_ms::float / sched.scheduled_ms)
            ELSE NULL END,
       NULL::bigint, NULL::bigint
FROM sched
LEFT JOIN present ON present.employee_id = sched.employee_id
ON CONFLICT (store_id, employee_id, date) DO UPDATE SET
    scheduled_duration_ms = EXCLUDED.scheduled_duration_ms,
    present_duration_ms   = EXCLUDED.present_duration_ms,
    presence_ratio        = EXCLUDED.presence_ratio
```
Notes:
- `visit_sessions` are closed by `shift_closer` before IEP5 runs, so `total_duration_ms` is
  populated. Join `global_id → global_identities.employee_id` (the link survives in
  `global_identities`; `visit_sessions` itself carries only `is_employee`).
- Employees with a shift but no linked presence get `present_duration_ms = NULL` /
  `presence_ratio = NULL` (LEFT JOIN), distinguishable from `0`.
- Keep the module docstring honest: presence/ratio now computed; punctuality/unassigned
  still NULL pending an employee↔zone-assignment model.

## Acceptance
- Targeted `staff_absence_employee` alert fires based on the **specific** employee's
  presence, not "any staff".
- After a shift with a linked employee, `daily_employee_summary` shows non-NULL
  `present_duration_ms` and a `presence_ratio` in `[0,1]`.
- An unlinked employee with a scheduled shift still produces a row (scheduled only, presence
  NULL) — no regression vs current behavior.
