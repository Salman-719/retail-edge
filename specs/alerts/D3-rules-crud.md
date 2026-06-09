# D3 — Alert Rules CRUD (+ severity)

_The rule is the thing everything else hangs on: IEP4 reads it to fire, the feed shows what fired,
the history remembers it. Today there is no way for a human to create one. This adds the CRUD —
with validation that mirrors the database's own guarantees, so the API can never write a rule IEP4
would choke on — plus the `severity` an operator picks per rule._

## Non-obvious tooling / facts

- `alert_rules` already has hard CHECK constraints
  ([0011](../../services/eep/alembic/versions/0011_alert_rules.py#L36)): per-type required field
  (`queue_buildup`→`people_threshold`, `staff_absence_zone`→`min_employees`,
  `staff_absence_employee`→`employee_id`) and `cooldown_minutes >= threshold_minutes`. The API
  validation must mirror these so the user gets a 422, not a 500 from the DB.
- There is **no SQLAlchemy model** for `alert_rules` (IEP4 uses raw SQL; EEP never had CRUD). Add one.
- IEP4 reads rules via raw SQL ([queries.py:150](../../services/iep4_alerts/app/persistence/queries.py#L150))
  — confirm the columns this CRUD writes match what IEP4 selects.
- `staff_absence_employee` rules do NOT use zones; `queue_buildup` and `staff_absence_zone` require
  at least one zone (via `alert_rule_zones`).
- New audit actions go straight into `AUDIT_ACTIONS` (no DB enum — [B1](../bugfixes-cleanup/B1-audit-action-validation.md)).

## Architectural map

```
alembic 00NN  ADD COLUMN severity TO alert_rules AND alerts (low/medium/high/critical)
models/alert_rule.py       (NEW) AlertRule + AlertRuleZone
schemas/alert_rule.py      (NEW) Create / Update / Response with per-type validators
api/routers/alerts.py      (NEW) rule CRUD endpoints (+ read/resolve from D1/D2)
api/__init__.py            (+) register alerts_router
services/iep4_alerts/...   (~) copy rule.severity onto the alert INSERT (cross-service)
```

## Read before implementing

- [0011_alert_rules.py](../../services/eep/alembic/versions/0011_alert_rules.py) (exact columns + CHECKs)
- [iep4_alerts/app/persistence/queries.py:150-235](../../services/iep4_alerts/app/persistence/queries.py#L150) (what IEP4 reads + the alert INSERT to amend for severity)
- [middleware/store_auth.py:143-163](../../services/eep/app/middleware/store_auth.py#L143) (gate helpers)
- a zone-ownership validation example in [draft.py](../../services/eep/app/api/routers/draft.py) (zones belong to the active version)

## Rules (verifiable)

1. **Migration**: add `severity VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN
   ('low','medium','high','critical'))` to **both** `alert_rules` and `alerts`. Update `schema.sql`
   to match. Forward-only.
2. **IEP4 change (cross-service)**: the alert INSERT copies the firing rule's `severity` onto the
   `alerts` row. Camera-health producers (CAT F) set their own severity. Without this, history
   severity is always the default.
3. **Models**: `AlertRule` (+ `severity`, the per-type optional fields, timestamps) and
   `AlertRuleZone`. Load zones eagerly for the response.
4. **Endpoints** (`/store/{slug}/alert-rules`, `get_store_context`, `require_owner_or_manager`;
   admin passes via A1):
   - `GET` list (all rules for the store, with their zones + `is_active`).
   - `POST` create.
   - `GET /{id}` one.
   - `PATCH /{id}` update (partial, incl. `is_active` toggle and zone set replacement).
   - `DELETE /{id}` (cascade drops `alert_rule_zones` + `alert_state`).
5. **Validation (mirror the DB + more), 422 on failure**:
   - `type` ∈ the three; per-type required field present (`people_threshold` / `min_employees` /
     `employee_id`).
   - `cooldown_minutes >= threshold_minutes`; all minute fields > 0.
   - `queue_buildup` and `staff_absence_zone` require ≥ 1 zone; `staff_absence_employee` requires
     **no** zones and a valid `employee_id` belonging to this store.
   - Every `zone_id` belongs to the store's **active** version.
   - `severity` ∈ the four.
6. **Audit**: `alert_rule_created` / `alert_rule_updated` / `alert_rule_deleted` (before/after
   state in the audit payload). Register all three in `AUDIT_ACTIONS`.
7. **Response shape**: include `id, type, name, severity, is_active, threshold_minutes,
   cooldown_minutes, followup_interval_minutes, only_during_shift, people_threshold, min_employees,
   employee_id (+name), zones:[{id,name}], created_at, updated_at`.

## Acceptance

- Creating each of the three types with valid params returns 201 and a row IEP4 can read and fire on.
- Omitting the per-type required field (e.g. `queue_buildup` without `people_threshold`) → 422,
  not a DB 500.
- `cooldown < threshold` → 422. A `staff_absence_employee` rule with zones → 422. A zone from a
  non-active version → 422.
- Toggling `is_active=false` stops IEP4 from firing it (it reads `is_active`).
- A fired alert carries the rule's `severity` (after the IEP4 change).
- Each mutation writes the matching audit row; the audit drift test still passes.

## Hard constraints & anti-patterns

- **Do NOT** let the API write a rule the DB CHECKs would reject — validate first, return 422.
- **Do NOT** expose `alert_state` via this CRUD — it is IEP4's runtime, not config.
- **Do NOT** widen the `alert_rules.type` CHECK to add new types here — v1 is the three (new types
  are IEP4 evaluator work, out of scope).
- Keep minutes as integers; no unit games.

## Pinned versions

Python 3.11 · PostgreSQL 16 · `fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` ·
`asyncpg==0.29.0` · `alembic==1.13.1` · Pydantic v2.
