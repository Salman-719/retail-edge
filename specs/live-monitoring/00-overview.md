# Live Monitoring (IEP3 → EEP → Frontend) — Design Agreement

_The Live Monitoring page is the store-at-a-glance: who is on the floor right now, where they are,
what's alerting, which cameras are up. Every number on it is currently mock. This CAT wires it to
the reconciled identity state IEP3 already maintains — honestly framed as "near-live" (one update
per ~60s window), not a per-frame illusion._

---

## What we read (no new tables)

- **`global_identities`** `WHERE state='active'` → `last_floor_x/y` (world metres), `is_employee`,
  `employee_id`, `first_seen_ts`, `last_seen_ts`. This is "who is here and where."
- **`active_person_state`** → `current_zone_id` per person (for the tooltip).
- **`employees`** → name for staff.
- **`alerts`** (active) → the alerts panel reuses D1's `/alerts/active`; the KPI uses a count.
- **`camera_status`** (in-memory, edge-reported, rebuilt from Redis on startup,
  [camera_status.py:42](../../services/eep/app/grpc_server/camera_status.py#L42)) → live per-camera
  status. **`edge_agents`** → device online + heartbeat age + version.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Freshness | **Near-live, ~60s** (IEP3/IEP4 window). Presented with a "last updated" indicator. No per-frame. |
| Poll cadence | **~60s**, aligned to the window (data doesn't change faster). |
| Staleness | Only show active persons with `last_seen_ts` within **~120s** (2 windows); older are dropped. |
| KPIs | Exactly four: `total_people`, `customers`, `staff_on_floor`, `active_alerts`. (No zone-occupancy list.) |
| Positions | Persons carry **world metres**; the frontend projects with the shared `worldToPixel` helper (same as E3 heatmap / zones). No second projection. |
| Person detail | **Hover tooltip only** (type, current zone, dwell-so-far, employee name). No click-through history in v1. |
| Camera health | `GET /cameras` + `camera_status.get_for_store` + the store's `edge_agent`. Not `camera_runtime_sessions` (historical). |
| Endpoint shape | One **`GET /live/overview`** (KPIs + persons) + **`GET /cameras/health`** + reuse **`/alerts/active`**. |

## Subpart map

| Spec | Scope |
|---|---|
| [F1-live-api.md](F1-live-api.md) | `GET /live/overview` — four KPIs + active persons (world coords + tooltip fields). |
| [F2-camera-health.md](F2-camera-health.md) | `GET /cameras/health` — per-camera live status + device/agent health. |
| [F-frontend.md](F-frontend.md) | Wire LiveMonitoring.jsx: poll 60s, project persons, reuse D1 alerts panel, real camera health. |

## Auth

Store-scoped via `get_store_context` (admin bypass [A1](../admin-rbac/A1-authz-core.md)). All
read-only — no migrations, no audit.

## Dependencies

- Person projection reuses the shared `worldToPixel` helper extracted in
  [E-frontend](../analytics/E-frontend.md) — coordinate it so both pages use one helper.
- The alerts panel reuses [D1](../alerts/D1-D2-read-resolve.md) `/alerts/active`.
- Customer/staff split is real only where punch-in linking is configured (already live in code).

## Implementation order

F1 + F2 (parallel) → F-frontend.
