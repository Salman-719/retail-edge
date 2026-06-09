# E-frontend — Wire Analytics.jsx to the real API

_Delete the mock. The Analytics page becomes a thin, honest view over the E1/E3 endpoints: one
shared control bar drives every widget; each widget lets the user flip chart↔table and export CSV.
No fabricated data, no second coordinate convention, no client-side re-aggregation that the API
deliberately refused to do._

## Non-obvious tooling / facts

- Charts: **recharts 3.8.1** (already a dep; includes `Sankey` for the flow widget). Heatmap overlay:
  **react-konva 18.2.10** (already used in [Analytics.jsx](../../frontend/src/pages/Analytics.jsx)).
- Skeletons exist ([Skeletons.jsx](../../frontend/src/components/Skeletons.jsx): `TableSkeleton`,
  `CardSkeleton`, `StatsSkeleton`).
- **No CSV library** — build a tiny `rows → Blob → download` util; do not add a dependency.
- `api.js` already has stale analytics stubs (`getHeatmap`, `getZoneTraffic`, `getTrends`) pointing
  at endpoint names we changed. **Replace them** with functions matching E1/E3.
- **No shared world→pixel helper exists** — the projection is inline in
  [StoreConfigEdit.jsx](../../frontend/src/pages/StoreConfigEdit.jsx). Extract it into a shared util
  so the heatmap overlay and zone rendering use ONE convention (the E3 alignment requirement).
- The current page already has the date presets + from/to pickers and a "Showing demo data" banner
  — reuse the pickers, **delete** the banner and every `build*Mock()`.

## Architectural map

```
pages/Analytics.jsx              rewrite: shared state + control bar + widgets, zero mock
components/analytics/
  AnalyticsControls.jsx          range presets + custom from/to + granularity + zone filter
  useAnalyticsQuery.js           hook: (endpoint, params) → {data, loading, error}; refetch on params
  WidgetFrame.jsx                title + chart/table toggle + CSV button wrapper
  StoreSeriesWidget / ZonesWidget / CompositionWidget / DistributionWidget /
  EmployeesWidget / FlowMatrixWidget / HeatmapWidget
lib/csv.js                       toCsv(rows, columns) + downloadCsv(filename, csv)
lib/floorProjection.js           worldToPixel(floorPlan) — extracted, reused by zones + heatmap
api.js                           getStoreSeries, getZoneAnalytics, getComposition, getDistribution,
                                 getEmployeeAnalytics, getFlowMatrix, getHeatmap  (replace stubs)
```

## Read before implementing

- [pages/Analytics.jsx](../../frontend/src/pages/Analytics.jsx) (what is replaced)
- [api.js:296-316](../../frontend/src/api.js#L296) (stale analytics stubs)
- [E1-read-api.md](E1-read-api.md) + [E3-heatmap-projection.md](E3-heatmap-projection.md) (the contracts)
- the inline world→pixel projection in StoreConfigEdit (extract, do not duplicate)

## Rules (verifiable)

### Shared control bar (drives all widgets)
1. `AnalyticsControls` owns: date range (presets Today/7d/30d/90d + custom `from`/`to`),
   `granularity` selector (`day | week | month | auto`), and a **zone multi-select** filter. These
   live in Analytics.jsx shared state and are passed to every widget; changing any one refetches all.
2. The employee filter lives on the Employees widget only (it is the only per-employee view).
3. Send `granularity` verbatim to the API; render the `grain` the API echoes back as the axis label
   (so `auto` is transparent to the user).

### Data + widgets (one endpoint each, no mock)
4. Replace all `build*Mock()` and the demo banner. Each widget calls its endpoint via
   `useAnalyticsQuery` and renders `rows` from the `{store_id, grain, from, to, rows}` envelope.
5. `api.js` functions (replace stubs), all `GET /store/{slug}/analytics/...`:
   `getStoreSeries`, `getZoneAnalytics`, `getComposition`, `getDistribution`,
   `getEmployeeAnalytics`, `getFlowMatrix`, `getHeatmap` — params `{from, to, granularity, zone_ids?,
   employee_ids?}`.
6. Widget → view mapping (default view first):
   - **StoreSeries**: line (toggle line/bar/area) with a **metric selector** (visits, unique
     visitors, avg/median duration, peak occupancy, dead periods) — one metric at a time to avoid
     mixed scales. + table + CSV.
   - **Zones**: grouped bar comparing zones for the selected metric (toggle bar/table) + CSV; honors
     the top-bar zone filter.
   - **Composition**: donut customers vs staff (fixed) + table + CSV.
   - **Distribution**: histogram bar + table + CSV.
   - **Employees**: table primary (+ optional per-row sparkline) + CSV; honors employee filter.
   - **FlowMatrix**: matrix/table default (from → to, count, probability) with an optional **Sankey**
     toggle (recharts `Sankey`) + CSV.
   - **Heatmap**: konva floor overlay (E3) driven by top-bar granularity; optional CSV of cells.
7. **Per-widget toggle**: `WidgetFrame` provides the chart↔table toggle and the CSV button uniformly.

### Heatmap projection (the E3 alignment requirement)
8. Extract a shared `worldToPixel(floorPlan)` from the zone-rendering code into `lib/floorProjection.js`
   and use it for BOTH zones and the heatmap overlay. The heatmap draws each cell by projecting its
   `world_*_min/max` rect; color via `intensity` (reuse the existing `heatColor`). Do NOT write a
   second projection.
9. If `floor_plan.image_uploaded` is false or `cells` is empty, show the existing
   "needs a configured floor plan" / "no data" placeholder — never a blank canvas.

### States
10. Loading → Skeletons. Empty (`rows: []`) → an explicit "No data for this range yet" state
    (distinct from zero). Buckets with `is_complete=false` → a "provisional" badge/marker.
11. Errors → inline error, never a silent fall-back to mock.

### CSV + formatting
12. `lib/csv.js`: `toCsv(rows, columns)` (escapes commas/quotes/newlines) + `downloadCsv(name, csv)`
    via `Blob` + object URL. Every widget's CSV exports exactly the rows it displays.
13. Durations arrive in **ms**; format to human-readable (s/min) in the UI only. Dates are ISO.
14. KPI cards (if kept): show the **most recent complete bucket** at the selected grain, NOT a
    range sum — never sum non-additive metrics client-side (Rule from [E1](E1-read-api.md)).

## Acceptance (verify at end of phase)

- Changing range/grain/zone in the top bar refetches and updates every widget; the URL/state is the
  single source (no per-widget date pickers).
- Every widget toggles chart↔table and exports a CSV matching the on-screen rows.
- `granularity=auto` labels axes with the grain the API returned (day for short ranges, month for a year).
- The heatmap cell at a known zone centroid renders inside that zone (shares the extracted projection).
- A store with no closed shifts shows "No data yet" everywhere (not zeros, not mock, not 404).
- The "Showing demo data" banner and all `build*Mock()` functions are gone from the bundle.
- Composition shows `staff=0` gracefully for a store with no punch station.

## Hard constraints & anti-patterns

- **NEVER** fall back to mock/synthetic data on error or empty — show the real state.
- **NEVER** re-aggregate non-additive metrics (uniques/averages/medians) client-side — render what
  the API returns; the API already chose the correct grain.
- **NEVER** add a second world→pixel formula — one extracted helper for zones and heatmap.
- **Do NOT** give each widget its own date/zone controls — one shared bar (user decision).
- **Do NOT** add a charting/CSV dependency — recharts + a Blob util cover it.
- Keep widgets dumb: they receive params + render rows; fetching/loading lives in `useAnalyticsQuery`.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · `recharts@^3.8.1` · `react-konva@^18.2.10` ·
`konva@^9.3.2` · `axios@^1.7.2` · `lucide-react@^1.17.0` — all already in `frontend/package.json`,
no additions.

## Hand-off

- **D7** (alerts-over-time) adds one more widget to this page after CAT D ships the `alerts` table +
  endpoint; it slots into the same control bar + WidgetFrame pattern.
