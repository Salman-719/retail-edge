# S3 — Punch Ingestion + Simulation

_A production-shaped webhook that a real punch machine would call, plus a DEBUG-mode dev
trigger to fire punches now. Both just persist a `pending` `punch_events` row; S4 resolves._

## Read before implementing
- [services/eep/app/api/__init__.py](../../services/eep/app/api/__init__.py) — router
  registration + the `if settings.DEBUG_MODE:` block for dev routers.
- [services/eep/app/api/routers/employees.py](../../services/eep/app/api/routers/employees.py)
  — store-scoped CRUD + `require_owner_or_manager` pattern; `_get_employee_or_404`.
- [services/eep/app/api/routers/dev_pipeline.py](../../services/eep/app/api/routers/dev_pipeline.py)
  — DEBUG dev-control conventions (`@router.post`, request models).
- [services/eep/app/middleware/store_auth.py](../../services/eep/app/middleware/store_auth.py)
  — `get_store_context`, `StoreContext`.

## Production endpoint — new router `routers/punch.py`
Register in `api/__init__.py` (non-DEBUG, under `/api`).

### `POST /store/{slug}/punch-events`
Body `PunchEventRequest` (`schemas/punch.py`):
```python
class PunchEventRequest(BaseModel):
    employee_code: str | None = None     # badge id a real machine knows
    employee_id:   uuid.UUID | None = None
    punched_at:    datetime | None = None  # ISO8601; default = now (UTC)
    # exactly one of employee_code / employee_id required
```
Logic:
1. Resolve the employee within the store: by `employee_id` or by `(store_id, employee_code)`.
   404 `EMPLOYEE_NOT_FOUND` if missing or inactive.
2. `punched_at_ms = int((punched_at or now_utc).timestamp() * 1000)`. Reject timestamps too
   far in the future (> a few seconds) → 422 `PUNCH_IN_FUTURE`.
3. Insert `punch_events(store_id, employee_id, punched_at_ms, source='device',
   status='pending')`. Return the created row (`PunchEventResponse`: id, employee_id,
   punched_at_ms, status).
4. Audit log `punch_recorded` (reuse `write_audit_log`; add the action to the audit enum if
   it is constrained — check `schema.sql` audit action CHECK around L100).

### Auth
MVP: protect with `get_store_context` (owner/manager) **or** a per-store device secret
header `X-Punch-Secret`. Implement a small dependency `verify_punch_source`:
- If `X-Punch-Secret` present → compare against `stores`/`store_settings` secret column
  (add nullable `punch_secret VARCHAR` to store settings if you want the device path; this
  is OPTIONAL for the simulation and may be deferred — document it).
- Else fall back to `get_store_context` + `require_owner_or_manager`.
For the simulation we use the authenticated path; the secret path is the real-machine hook.
**Keep it simple — do not block S3 on a full device-auth system; a `TODO` note is acceptable.**

## Dev trigger — `dev_pipeline.py` (DEBUG only)
### `POST /api/dev/punch`
Body: `{ store_id: str, employee_id: str, at?: ISO8601 }`.
Insert `punch_events(..., source='simulated', status='pending',
punched_at_ms = at or now_ms)`. Return the row. This is the endpoint a dev UI "Punch in"
button calls. No auth beyond DEBUG gating (matches existing dev_pipeline endpoints).

Optional convenience: `POST /api/dev/punch/by-code` taking `employee_code` for parity with
the production endpoint.

## Schemas (`schemas/punch.py`)
`PunchEventRequest`, `PunchEventResponse`, and the dev `DevPunchRequest`.

## Read-back endpoint (optional, recommended for verifying S4)
`GET /store/{slug}/punch-events?status=&limit=` → recent punch_events with their status,
linked_global_id, match_distance_m. Useful to watch the resolver work end-to-end.

## Acceptance
- `POST /store/{slug}/punch-events` with a valid employee creates a `pending` row;
  unknown/foreign employee → 404; future timestamp → 422.
- `POST /api/dev/punch` (DEBUG) creates a `simulated` `pending` row at now().
- Both are inert until S4 runs (status stays `pending`).
