# F1 — Live Overview API

_One cheap snapshot per ~60s window: four numbers and the dots on the map. Read the reconciled
identity state IEP3 already keeps; don't invent a realtime layer it never had._

## Non-obvious tooling / facts

- `global_identities` is indexed `(store_id, state)` — the `state='active'` scan is cheap.
- `last_floor_x/y` are **world metres** (homography output), nullable until a person has a floor
  fix. `active_person_state.current_zone_id` gives the live zone.
- IEP3 lags moving `active → lost`; apply a `last_seen_ts` staleness cut (~120s) so the snapshot
  doesn't show ghosts.
- The page already loads the active version's floor plan (via `getActiveVersion`), so persons need
  only **world coords** — the frontend already has the projection metadata.
- `active_alerts` count = `alerts WHERE resolved_at IS NULL` (the panel list still uses D1).

## Architectural map

```
api/routers/live.py     (NEW)  GET /store/{slug}/live/overview
schemas/live.py         (NEW)  LiveOverview { kpis, persons[], generated_at_ms }
api/__init__.py         (+)    register live_router
```

## Read before implementing

- [schema.sql global_identities](../../services/eep/schema.sql#L801) (`state`, `last_floor_x/y`, `first_seen_ts`, `last_seen_ts`, `is_employee`, `employee_id`)
- [0010 active_person_state](../../services/eep/alembic/versions/0010_analytics_foundation.py#L148) (`current_zone_id`)
- [middleware/store_auth.py:86](../../services/eep/app/middleware/store_auth.py#L86)

## Rules (verifiable)

1. **`GET /store/{slug}/live/overview`** (`get_store_context`; admin via A1), returns
   `{ generated_at_ms, kpis, persons }`.
2. **Staleness**: consider a person "present" iff `state='active'` AND
   `last_seen_ts >= now_ms - STALE_MS` (`STALE_MS` default 120000, from settings). Apply the SAME
   filter to KPIs and persons so counts match the dots.
3. **KPIs** (exactly four):
   - `total_people` = present count.
   - `customers` = present AND `is_employee=false`.
   - `staff_on_floor` = present AND `is_employee=true`.
   - `active_alerts` = `COUNT(alerts WHERE store_id=? AND resolved_at IS NULL)`.
4. **Persons**: one row per present person:
   `{ global_id, type: 'customer'|'staff', world_x, world_y, current_zone_id, current_zone_name,
   employee_name (null for customers), dwell_ms }` where `dwell_ms = now_ms - first_seen_ts`.
   Omit persons with null `last_floor_x/y` from the map list (they can't be placed) but still count
   them in KPIs — or document the choice; default: **count in KPIs, omit from `persons`**.
5. Join `zones.name` for `current_zone_name` and `employees` for `employee_name`. `current_zone_id`
   may be null (person not in a zone) — return null, not an error.
6. `generated_at_ms` = server now, so the frontend can render "last updated Xs ago".
7. Read-only; no audit, no migration.

## Acceptance

- With N active persons in the last window, `total_people=N`, `customers+staff_on_floor=N`, and
  `persons` has one entry per placeable person.
- A person last seen 3 minutes ago (> staleness) is excluded from both KPIs and `persons`.
- Staff rows carry `employee_name`; customers carry null.
- `dwell_ms` increases across polls for a person who stays.
- A super-admin can call it for any store.

## Hard constraints & anti-patterns

- **NEVER** read `global_tracking_history` per-frame here — this is the reconciled active set, ~60s.
- **NEVER** project to pixels server-side — return world metres; the frontend owns projection
  (shared helper, one convention).
- KPIs and `persons` MUST use the identical staleness filter — mismatched counts erode trust.
- Keep it one query pass where possible; this endpoint is polled every ~60s per open store.

## Pinned versions

`fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · Pydantic v2.
