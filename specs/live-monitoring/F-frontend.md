# F-frontend — Wire LiveMonitoring.jsx

_Replace every mock on the live page with the real near-live snapshot: four KPIs, dots on the floor
plan, the active-alerts feed, and true camera health — refreshed each window with an honest "last
updated" stamp._

## Non-obvious tooling / facts

- The page already renders the floor plan + zones via Konva (`FloorPlanCanvas`,
  [LiveMonitoring.jsx:74](../../frontend/src/pages/LiveMonitoring.jsx#L74)) and loads the active
  version. It only lacks real data and the world→pixel projection for persons.
- It currently mocks `MOCK_KPI`, `MOCK_PEOPLE` (already pixel coords), `MOCK_ALERTS_INIT`,
  `MOCK_CAMERAS`, and shows a "demo data" banner — all removed.
- `api.js` has a `getLiveSummary` stub → repurpose to the real endpoints. `getActiveAlerts` exists
  (reused for the alerts panel).
- Persons arrive as **world metres** — project with the shared `worldToPixel` helper from
  [E-frontend](../analytics/E-frontend.md). One helper for zones, heatmap, and persons.

## Architectural map

```
pages/LiveMonitoring.jsx   rewrite data layer: poll overview + camera health; reuse alerts
api.js                     + getLiveOverview, getCameraHealth ; reuse getActiveAlerts
lib/floorProjection.js     reuse worldToPixel (shared with Analytics/zones)
components/                small: KpiCards, CameraHealthPanel (or inline)
```

## Read before implementing

- [pages/LiveMonitoring.jsx](../../frontend/src/pages/LiveMonitoring.jsx) (what's replaced)
- [F1-live-api.md](F1-live-api.md), [F2-camera-health.md](F2-camera-health.md), [D1-D2](../alerts/D1-D2-read-resolve.md)

## Rules (verifiable)

1. **api.js**: add `getLiveOverview(slug)` → `/live/overview`, `getCameraHealth(slug)` →
   `/cameras/health`. Remove/repurpose the `getLiveSummary` stub. Keep `getActiveAlerts`.
2. **Polling**: poll `getLiveOverview` and `getCameraHealth` every **~60s** (window cadence) and
   `getActiveAlerts` likewise; clear timers on unmount. Show **"updated Xs ago"** from
   `generated_at_ms`.
3. **KPIs**: render the four (`total_people`, `customers`, `staff_on_floor`, `active_alerts`) from
   the overview. No zone-occupancy list (locked).
4. **Persons on map**: project each `{world_x, world_y}` with `worldToPixel(floorPlan)` (floorPlan
   from the already-loaded active version) — color customer vs staff, **hover tooltip** showing
   type, `current_zone_name`, `dwell_ms` (formatted), and `employee_name` for staff. No click-through.
5. **Alerts panel**: list `getActiveAlerts`; each item links/dismisses via the D1/D2 endpoints
   (reuse, do not re-implement). (LiveMonitoring shares this with the Alerts page.)
6. **Camera health panel**: render `getCameraHealth.cameras` (name + status + online color) and the
   `agent` block (online + "last seen"); show `unknown` cameras distinctly.
7. **Remove** all `MOCK_*` and the demo banner. Loading→skeletons; empty (no people)→an explicit
   "No one on the floor right now" state; errors inline (never mock fallback).

## Acceptance

- KPIs and dots match the `/live/overview` snapshot and refresh each ~60s with an updated timestamp.
- A person dot at a known zone renders inside that zone (shares the projection helper — same proof
  as the heatmap).
- Hover shows the person's zone, dwell, and (for staff) name.
- Camera panel shows real online/offline + `unknown` for never-started cameras; agent "last seen"
  grows when the device is quiet.
- Dismissing an alert here removes it (via D2) and it leaves the panel.
- No mock/demo data remains in the bundle.

## Hard constraints & anti-patterns

- **NEVER** fall back to mock on empty/error — show the real state ("No one on the floor").
- **NEVER** add a second world→pixel formula — reuse the shared helper (zones/heatmap/persons).
- **Do NOT** poll faster than the data changes — ~60s is the window; tighter just burns requests.
- **Do NOT** re-implement alerts list/dismiss — reuse D1/D2.

## Pinned versions

`react@^18.2.0` · `react-konva@^18.2.10` · `konva@^9.3.2` · `axios@^1.7.2` ·
`lucide-react@^1.17.0` — all present, no additions.
