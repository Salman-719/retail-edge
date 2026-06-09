# B1 — Audit Action Validation (drop DB enum, validate in app)

_Stop shipping endpoints that 500 because someone forgot to extend a hand-maintained
SQL `CHECK` list. Make the set of valid audit actions a single Python source of truth,
enforced at write time and guarded by a drift test, so adding an audited action in a
future feature is a one-line registry edit — never a migration, never a production
incident._

---

## Why this exists (the live bug)

`audit_logs.action` carries a `CHECK (action IN (...))` enum ([schema.sql:97](../../services/eep/schema.sql#L97)).
The code already emits **7 actions that are not in that enum**, so every one of those
endpoints inserts the business row, then the audit insert raises
`asyncpg.exceptions.CheckViolationError` inside `db.flush()` and rolls back the whole
transaction. Confirmed reproduction: **creating a shift pattern** from the Employees page
→ `audit_logs_action_check` violation on action `shift_pattern_created`.

Missing-but-emitted actions (all currently broken):

```
store_deleted
shift_pattern_created   shift_pattern_updated   shift_pattern_deleted
shift_employee_assigned shift_attendance_updated
break_created
```

This is a recurring class of bug: migration [0012](../../services/eep/alembic/versions/0012_crs_stop_reason_eep_restart.py)
already had to widen a *different* `CHECK` enum (`camera_runtime_sessions.stop_reason`)
for the same reason. **The fix is to stop using a DB enum for this**, not to widen it again.

---

## Non-obvious tooling / repo facts

- **Alembic is authoritative; `schema.sql` is "fast dev reset only"** (see comment at
  [docker-compose.yml:28](../../docker-compose.yml#L28)). Both must be changed: a migration
  for existing DBs, `schema.sql` for fresh installs. They must agree.
- Migration head is **`0014`** ([0014_employee_linking.py](../../services/eep/alembic/versions/0014_employee_linking.py)).
  This spec adds **`0015`** (`down_revision = "0014"`). Migrations connect via psycopg2 on
  `ALEMBIC_DATABASE_URL` (bypasses PgBouncer).
- Audit writes go through one chokepoint: `write_audit_log()`
  ([audit.py:9](../../services/eep/app/core/audit.py#L9)). It is called in the **same
  transaction** as the business operation (fail-closed by design — keep it that way).
- Action column is `VARCHAR(50)`; longest current action is 24 chars. Keep the 50 cap.

## Architectural map

```
app/core/audit_actions.py   (NEW) — AUDIT_ACTIONS: frozenset[str]  ← single source of truth
        ▲ imported by
app/core/audit.py           — write_audit_log() validates action ∈ AUDIT_ACTIONS, else ValueError
        ▲ called by
routers: auth, stores, members, config, draft, shifts, employees, settings  (8 emitters)

alembic/versions/0015_drop_audit_action_check.py  (NEW) — DROP CONSTRAINT, no re-add
services/eep/schema.sql:97-106                     — replace CHECK clause with plain column
tests/unit/eep/test_audit_actions.py               (NEW) — drift guard
```

## Read before implementing

- [services/eep/app/core/audit.py](../../services/eep/app/core/audit.py)
- [services/eep/schema.sql:93-112](../../services/eep/schema.sql#L93) (the `audit_logs` table)
- [services/eep/alembic/versions/0012_crs_stop_reason_eep_restart.py](../../services/eep/alembic/versions/0012_crs_stop_reason_eep_restart.py) (style for an idempotent constraint migration)
- Honor the repo rule: read each target file first; if reality differs from this spec, report the deviation before coding.

---

## Rules (verifiable)

1. **Create `app/core/audit_actions.py`** exposing `AUDIT_ACTIONS: frozenset[str]` containing
   the complete canonical set below. Group with comments. This file is the ONLY place the set
   is defined.

   Existing (already allowed by the old enum) — keep all:
   ```
   login  logout  password_reset  permission_changed
   store_created  store_updated  store_deleted
   config_edited  version_activated  version_rolled_back
   draft_created  draft_discarded  draft_expired
   member_invited  member_removed  member_role_changed
   employee_created  employee_updated  employee_deleted
   shift_created  shift_updated  shift_deleted
   ```
   Add (emitted by code, were missing — this is what unbreaks the endpoints):
   ```
   shift_pattern_created  shift_pattern_updated  shift_pattern_deleted
   shift_employee_assigned  shift_attendance_updated  break_created
   ```

2. **`write_audit_log()` validates** `action`: if `action not in AUDIT_ACTIONS`, raise
   `ValueError(f"Unregistered audit action {action!r}; add it to app/core/audit_actions.py")`
   **before** constructing the `AuditLog` row. Fail fast at the source — do not silently drop.

3. **Migration `0015_drop_audit_action_check.py`** (`revision="0015"`, `down_revision="0014"`):
   - `upgrade()`: `ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check;`
     (idempotent; safe whether or not the constraint exists).
   - `downgrade()`: re-add the constraint with the **original** enum only (the 21 existing
     actions, NOT the new 6) so downgrade is a faithful inverse.
   - Forward-only, no data migration needed.

4. **`schema.sql`**: replace the `CHECK (action IN (...))` clause (lines 97–106) with:
   `action VARCHAR(50) NOT NULL,  -- validated in app: app/core/audit_actions.py (AUDIT_ACTIONS)`.
   Fresh installs must match post-migration state.

5. **Drift guard test `tests/unit/eep/test_audit_actions.py`** (pytest, no DB): statically scan
   every `services/eep/app/api/routers/*.py` and `services/eep/app/core/*.py` for
   `write_audit_log(` calls, extract the action string literal (first positional arg after `db`,
   or `action=`), and assert each extracted action ∈ `AUDIT_ACTIONS`. This converts "forgot to
   register an action" from a production 500 into a failing unit test. Use `ast` or a targeted
   regex; the call sites pass the action as a string literal (verified — no dynamic actions).

## Acceptance (must verify at end of phase)

- `POST /store/{slug}/shift-patterns` returns **201** and writes an `audit_logs` row with
  `action='shift_pattern_created'` (the original repro now passes).
- The other 6 previously-broken endpoints succeed (shift create/update/delete, shift
  assignment, attendance update, break create, store delete).
- `pytest tests/unit/eep/test_audit_actions.py` passes; deliberately introducing an
  unregistered action in a router makes it fail.
- `alembic upgrade head` then `alembic downgrade -1` both run clean on a populated DB.

## Hard constraints & anti-patterns

- **Do NOT re-introduce a DB `CHECK` enum on `action`** (or any new table's action-like
  column). That is the exact recurring bug this spec removes; 0012 is the cautionary precedent.
- **Do NOT change the transaction boundary** — audit stays in the same transaction as the
  business write (fail-closed). This spec changes *what is valid*, not *when it commits*.
- **Do NOT swallow audit failures** (no try/except that lets the action proceed unaudited).
- Action strings stay `snake_case`, ≤ 50 chars, `entity_type`-aligned. No spaces, no caps.
- One source of truth only: never duplicate the action list in a router, a Pydantic enum, and
  the DB. The registry is it.

## Pinned versions (the running stack — do not bump in this spec)

- Python 3.11 · PostgreSQL 16
- `fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0`
- `alembic==1.13.1` · `psycopg2-binary==2.9.9` · `pydantic-settings==2.2.1`
- `pytest` (asyncio) per existing `tests/` suite

## Out of scope (later, same CAT B)

- B3 delete LiveView, B4 delete VisionDebugConsole — separate spec at step 8.
- New audited actions for Admin (CAT A) and Alerts (CAT D) will simply be **added to
  `AUDIT_ACTIONS`** when those specs land — no schema work, by design of this spec.
