# D1 + D2 — Alerts Read & Resolve

_IEP4 writes alerts into the dark. This is the window: list what's firing now, browse what fired
before, dismiss one by hand. Generic over every alert type so the camera alerts CAT F adds later
appear without touching this code._

## Non-obvious tooling / facts

- Active = `resolved_at IS NULL`. History = resolved. IEP4 already auto-resolves
  (`resolution='auto_detected'`); a user dismiss is `manual_dismiss` + `resolved_by`
  ([queries.py:236](../../services/iep4_alerts/app/persistence/queries.py#L236)).
- The frontend already declares the endpoints: `getActiveAlerts → /alerts/active`,
  `resolveAlert → /alerts/{id}/resolve` ([api.js:301-305](../../frontend/src/api.js#L301)), and the
  sidebar polls `getActiveAlerts` for its badge. **Match these paths.**
- `details` is type-specific JSONB written by IEP4 — return it verbatim; the UI renders per type.
- This read API is **shared with LiveMonitoring** (CAT F) — its active-alerts panel calls the same
  `/alerts/active`.

## Architectural map

```
api/routers/alerts.py  (+, same router as D3)
  GET  /store/{slug}/alerts/active
  GET  /store/{slug}/alerts/history     ?from&to&type&severity&resolution
  GET  /store/{slug}/alerts/{id}
  POST /store/{slug}/alerts/{id}/resolve
schemas/alert.py       (NEW) AlertResponse (joined names + rule + severity)
```

## Read before implementing

- [schema.sql:390-405](../../services/eep/schema.sql#L390) (`alerts` columns)
- [api.js:296-305](../../frontend/src/api.js#L296) (the paths to match)
- D3 (severity column must exist first)

## Rules (verifiable)

1. **`GET /alerts/active`** → all unresolved alerts for the store, newest first. Each row:
   `id, type, severity, zone_id (+name), employee_id (+name), details, created_at, is_followup,
   alert_rule_id (+rule name)`. Join zones/employees/alert_rules for labels. Returns `[]` when none
   (the badge reads length).
2. **`GET /alerts/history`** `?from&to&type&severity&resolution` → resolved (and optionally all)
   alerts in the window, newest first, with the same shape plus `resolved_at, resolution,
   resolved_by (+name)`. Paginate (limit/offset, sane default e.g. 100) — history grows unbounded.
3. **`GET /alerts/{id}`** → one alert, full detail; 404 if not in this store.
4. **`POST /alerts/{id}/resolve`** (`require_owner_or_manager`): set `resolved_at=now()`,
   `resolution='manual_dismiss'`, `resolved_by=ctx.user_id`. **Idempotent**: if already resolved,
   return the current state (200) without overwriting an earlier `auto_detected`/`resolved_by`.
   Write audit `alert_dismissed`.
5. **Reads gate**: any store member (`get_store_context`, no role requirement); admin via A1.
6. **Generic over type**: never special-case the three rule types or the camera types in the read
   path — shape is uniform; `details` carries the specifics.
7. Register `alert_dismissed` in `AUDIT_ACTIONS`.

## Acceptance

- With an active alert present, `/alerts/active` returns it; after `POST .../resolve` it leaves
  `/alerts/active` and appears in `/alerts/history` with `resolution='manual_dismiss'` and the
  dismisser's id.
- Resolving an already-auto-resolved alert does not clobber `auto_detected` (idempotent, 200).
- `/alerts/history?type=queue_buildup&from=..&to=..` filters correctly and paginates.
- The sidebar badge count equals `/alerts/active` length.
- A camera-type alert (once CAT F produces one) appears in both endpoints with no code change here.

## Hard constraints & anti-patterns

- **Do NOT** let resolve overwrite an existing resolution — auto-resolution wins if it already fired.
- **Do NOT** return unbounded history without pagination.
- **Do NOT** reshape per type — one uniform `AlertResponse`.
- **Do NOT** mutate `alert_state` here (that's IEP4's).

## Pinned versions

`fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · Pydantic v2.
