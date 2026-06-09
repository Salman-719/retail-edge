# E1 — Analytics Read API (router + grain resolver + rollup endpoints)

_Serve what IEP5 already computed, exactly as it was computed. One shared resolver turns
(range, granularity) into "read this precomputed table"; the endpoints are thin reads over the
`analytics.*` rollups with zone/employee names joined in. The discipline is honesty: each grain
reads its own table, and non-additive metrics are never summed at read time._

## Non-obvious tooling / facts

- `analytics.*` tables exist (migration [0010](../../services/eep/alembic/versions/0010_analytics_foundation.py));
  this spec adds **no migration** — it is read-only.
- Summaries are keyed by store-local `DATE` (IEP5 `shift_date` is store-local). Range filters use
  store-local dates; the store timezone lives on `stores.timezone`.
- `peak_occupancy_at_ms` exists on **daily** store summary only (not weekly/monthly).
- Weekly tables key on `(iso_year, iso_week, week_start_date)`, monthly on `(year, month,
  month_start_date)`, and carry `is_complete` (partial current period = `false`).
- Medians/averages are **precomputed per bucket** — never compute percentiles at read time.
- Store-scoped auth + admin bypass already exist ([store_auth.py](../../services/eep/app/middleware/store_auth.py),
  [A1](../admin-rbac/A1-authz-core.md)). Reuse `get_store_context`.

## Architectural map

```
api/routers/analytics.py        (NEW)  prefix /api, all routes /store/{slug}/analytics/...
core/analytics_grains.py        (NEW)  resolve_grain(range, granularity) → (grain, table-set, buckets)
schemas/analytics.py            (NEW)  response models (typed rows + envelope)
api/__init__.py                 (+)    register analytics_router
```

## Read before implementing

- [alembic/versions/0010_analytics_foundation.py:235-507](../../services/eep/alembic/versions/0010_analytics_foundation.py#L235) (exact columns)
- [middleware/store_auth.py:86-140](../../services/eep/app/middleware/store_auth.py#L86)
- [models/zone.py](../../services/eep/app/models/zone.py) and the employees model (for name joins)
- [aggregators/visits.py](../../services/iep5_analytics/app/aggregators/visits.py) (confirms visits = customers only)

## Rules (verifiable)

### Shared resolver (`core/analytics_grains.py`)
1. `resolve_grain(from_date, to_date, granularity)`:
   - `granularity="day"` → daily tables, one bucket per date in `[from, to]`.
   - `"week"` → weekly tables, ISO weeks intersecting the range.
   - `"month"` → monthly tables, months intersecting the range.
   - `"auto"` → `day` if span ≤ 31 days, `week` if ≤ 182 days, else `month`.
   - Returns the chosen grain + the bucket key list. Endpoints select rows by grain.
2. **Never re-aggregate non-additive metrics across buckets.** Additive (`total_visits`,
   `total_transitions`, `passthrough_count`, `engagement_count`, `dead_period_count`) MAY be
   summed for a range total. Non-additive (`unique_visitors`, `avg_*`, `median_*`,
   `presence_ratio`, `probability`, `peak_occupancy`) are returned **per bucket only**; for a
   single range-level non-additive number, read the matching week/month rollup row, never sum.
3. Validate `from ≤ to`, cap range span (e.g. ≤ 730 days) → `422` otherwise.

### Endpoints (all `GET /store/{slug}/analytics/...`, `get_store_context`)
4. **`/store-series`** `?from&to&granularity` → ordered series of
   `{bucket_start (date), total_visits, unique_visitors, avg_visit_duration_ms,
   median_visit_duration_ms, peak_occupancy, dead_period_count, dead_period_total_ms,
   is_complete}` from the grain's store-summary table. (`peak_occupancy_at_ms` included only for
   `day`.) This single payload feeds line/bar/area on the frontend.
5. **`/zones`** `?from&to&granularity&zone_ids=` → per-zone series:
   `{zone_id, zone_name, bucket_start, unique_visitors, total_transitions, avg_dwell_ms,
   median_dwell_ms, max_concurrent, passthrough_count, engagement_count, alert_trigger_count,
   is_complete}` from the grain's zone-summary table, joined to `zones.name`, optionally filtered
   to `zone_ids`. Frontend renders zone comparison (bar/table) per bucket or trend per zone.
6. **`/composition`** `?from&to&granularity` → for each bucket
   `{bucket_start, customers, staff, is_complete}` where `customers` = store-summary
   `unique_visitors`, `staff` = distinct employees with `present_duration_ms > 0` in
   `*_employee_summary` for the bucket. Feeds the donut. (See classification definition in
   [00-overview](00-overview.md).)
7. **`/distribution`** `?from&to` → visit-duration histogram. Buckets are **daily**; for a multi-day
   range, sum `visit_count` per `bucket_label` (counts are additive) and return ordered
   `{bucket_label, bucket_min_ms, bucket_max_ms, visit_count}`. Feeds a histogram.
8. **`/employees`** `?from&to&granularity&employee_ids=` → per-employee series:
   `{employee_id, employee_name, bucket_start, scheduled_duration_ms, present_duration_ms,
   presence_ratio, zone_punctuality_delay_ms, unassigned_zone_time_ms, is_complete}` from the
   grain's employee-summary table, joined to employee name. Feeds the employee table + drilldown.
9. **`/flow-matrix`** `?from&to` → zone sequence. Buckets are **daily**; for a range, sum
   `transition_count` per `(from_zone_id, to_zone_id)` (additive) and recompute `probability`
   = `count / sum(count) from each from_zone`. Return `{from_zone_id, from_zone_name, to_zone_id,
   to_zone_name, transition_count, probability}`. Feeds Sankey/matrix/table.
10. **Heatmap and alerts-over-time are NOT in this spec** — heatmap is
    [E3](E3-heatmap-projection.md); alerts-over-time is served by this router but reads the
    `alerts` table and is specced with CAT D.

### Empty / partial states (absorbs old E5)
11. A bucket with no IEP5 summary row (shift not closed / empty day) is **omitted** from the
    series, not returned as zeros — the frontend distinguishes "no data yet" from "zero traffic."
    Endpoints return `200` with an empty array when the whole range has no rows (never `404`).
12. Partial current week/month rows are returned with `is_complete=false` so the frontend can
    mark them provisional.

### Response envelope
13. Every endpoint returns `{ store_id, grain, from, to, rows: [...] }` (grain echoes the resolved
    grain so the frontend can label axes and `auto` is transparent). Durations stay in **ms**
    (frontend formats); dates are ISO `YYYY-MM-DD`.

## Acceptance (verify at end of phase)

- `/store-series?from=..&to=..&granularity=day` returns one row per day that has a summary, with
  values identical to the underlying `analytics.daily_store_summary` rows (no recomputation).
- Same endpoint with `granularity=week` reads `weekly_store_summary` (uniques/medians differ from
  a naive daily sum — proving non-additive metrics are not summed).
- `granularity=auto` over a 7-day range resolves to `day`; over 1 year resolves to `month`.
- `/composition` shows customers from store summary and staff from employee summary; with no punch
  station configured, `staff=0` and `customers>0` (still valid).
- `/zones?zone_ids=A,B` returns only zones A and B; `/employees` joins names.
- An all-empty range returns `200 {rows: []}`.
- A super-admin can call all endpoints for a store they don't belong to.

## Hard constraints & anti-patterns

- **NEVER** sum or average non-additive metrics across buckets (Rule 2). This is the one bug that
  silently corrupts every dashboard number — guard it with a test that compares a weekly endpoint
  result against the precomputed weekly row, not against summed dailies.
- **NEVER** query `global_tracking_history` or recompute percentiles in these endpoints — read the
  rollups. (Heavier raw access, if ever needed, is a separate, explicitly-scoped endpoint.)
- **Do NOT** return zero-filled rows for missing buckets (Rule 11) — it erases the "no data" signal.
- **Do NOT** invent a single range-level `unique_visitors` — expose per-bucket or the matching
  rollup grain.
- Keep all money/time units raw (ms, ints); no locale formatting server-side.
- One router, thin reads; aggregation logic that IEP5 owns must not creep back into EEP.

## Pinned versions

Python 3.11 · PostgreSQL 16 + TimescaleDB · `fastapi==0.115.0` ·
`sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · Pydantic v2 (`pydantic-settings==2.2.1`).
