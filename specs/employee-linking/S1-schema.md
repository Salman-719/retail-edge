# S1 — Schema & Data Model

_New Alembic migration `0013_employee_linking.py` (head is `0012`, see
[0012_crs_stop_reason_eep_restart.py](../../services/eep/alembic/versions/0012_crs_stop_reason_eep_restart.py)).
Mirror the corresponding `schema.sql` blocks so fresh `initdb` databases match. All
position values are **world metres** (consistent with the P1 coordinate-system fix)._

## Read before implementing
- [services/eep/schema.sql](../../services/eep/schema.sql) — `global_identities`
  (L794), `employees` (L306), `employee_embeddings` (L333).
- [services/eep/alembic/versions/0010_analytics_foundation.py](../../services/eep/alembic/versions/0010_analytics_foundation.py)
  — `op.execute("""CREATE TABLE IF NOT EXISTS …""")` idempotent style to copy.
- **Runtime verify:** `\d global_identities` on the running DB to confirm `is_employee`
  is absent (expected). The `ADD COLUMN IF NOT EXISTS` is safe regardless.

## Migration header
```python
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None
```
`downgrade()` may `raise NotImplementedError("forward-only")` (matches 0010).

## Change 1 — `global_identities`: add the link columns (repairs the IEP4 gap)
```sql
ALTER TABLE global_identities
    ADD COLUMN IF NOT EXISTS is_employee BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES employees(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_global_identities_employee
    ON global_identities(employee_id) WHERE employee_id IS NOT NULL;
```
- `is_employee` makes IEP4's existing `GET_DELTA` (`gi.is_employee`) valid.
- `employee_id` is the new specific link. `ON DELETE SET NULL` so deleting an employee
  preserves tracking history.
- **Also edit `schema.sql`** `global_identities` CREATE TABLE (L794) to include both
  columns inline for fresh DBs.

## Change 2 — `punch_in_stations` (per config version)
One station per version for MVP (a store has one punch machine). Keyed by `version_id`
so it flows through draft → activate exactly like zones/camera_configs (the active
version's rows simply become live when the version status flips — no orchestrator change).
```sql
CREATE TABLE IF NOT EXISTS punch_in_stations (
    id               UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id       UUID             NOT NULL REFERENCES store_config_versions(id) ON DELETE CASCADE,
    store_id         UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_config_id UUID             NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    world_x          DOUBLE PRECISION NOT NULL,            -- metres
    world_y          DOUBLE PRECISION NOT NULL,            -- metres
    radius_m         DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT uq_punch_station_per_version UNIQUE (version_id),
    CONSTRAINT positive_radius CHECK (radius_m > 0)
);
CREATE INDEX IF NOT EXISTS idx_punch_stations_version ON punch_in_stations(version_id);
```
Add the same block to `schema.sql` (Domain 5 area, after `employees`/`employee_embeddings`).

## Change 3 — `punch_events`
```sql
CREATE TABLE IF NOT EXISTS punch_events (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    employee_id      UUID        NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    punched_at_ms    BIGINT      NOT NULL,                 -- epoch ms; aligns with global_tracking_history.timestamp_ms
    source           VARCHAR(20) NOT NULL DEFAULT 'device'
                     CHECK (source IN ('device', 'simulated')),
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'linked', 'unmatched', 'expired')),
    linked_global_id UUID        REFERENCES global_identities(global_id) ON DELETE SET NULL,
    match_distance_m DOUBLE PRECISION,
    attempts         INTEGER     NOT NULL DEFAULT 0,
    last_attempt_at  TIMESTAMPTZ,
    resolved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_punch_events_pending
    ON punch_events(store_id, punched_at_ms) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_punch_events_employee
    ON punch_events(employee_id, punched_at_ms DESC);
```
Status lifecycle (owned by S4 resolver):
`pending` → `linked` (matched) | `unmatched` (max-wait elapsed, no match) | `expired`
(safety: never became eligible — should not occur in practice).

Add the same block to `schema.sql`.

## Change 4 — `active_person_state`: carry the specific `employee_id`
`active_person_state` is created in migration `0010`
([0010_analytics_foundation.py:151](../../services/eep/alembic/versions/0010_analytics_foundation.py#L151))
and already has `is_employee`. Add the specific link so IEP4 live state and direct queries
know *which* employee — not just that one is present:
```sql
ALTER TABLE active_person_state
    ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES employees(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_aps_store_employee_id
    ON active_person_state(store_id, employee_id) WHERE employee_id IS NOT NULL;
```
- Not in `schema.sql` (the table is migration-only, per the 0010 docstring).
- The S4 resolver sets it immediately on link; IEP4's `GET_DELTA`/`UPSERT_ACTIVE_PERSON_STATE`
  carry it forward for all subsequent writes (S5).
- Historical tables (`zone_transition_log`, `visit_sessions`) deliberately do **not** get a
  snapshot column — IEP5 derives `employee_id` retroactively by joining
  `global_id → global_identities.employee_id`, which the resolver sets atomically and which
  therefore covers that identity's *entire* history, including rows written before the punch.

## ORM models (SQLAlchemy, EEP)
Add under `services/eep/app/models/`:
- `punch_in_station.py` → `PunchInStation`
- `punch_event.py` → `PunchEvent`
- Extend the existing `GlobalIdentity` model if one exists; if global_identities has no
  ORM model (IEP3 uses raw asyncpg, EEP may not map it), no EEP model is required —
  draft.py and resolver use raw SQL / new models only. **Check** `models/` for an existing
  `global_identity.py` before adding columns to an ORM class.

## Acceptance
- `alembic upgrade head` applies cleanly on an existing dev DB and is replay-safe.
- `\d global_identities` shows `is_employee`, `employee_id`; IEP4 `GET_DELTA` runs without
  "column does not exist".
- Fresh DB from `schema.sql` contains all three changes.
