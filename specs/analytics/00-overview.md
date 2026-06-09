# Analytics (IEP5 → EEP → Frontend) — Design Agreement

_IEP5 already computes a rich daily/weekly/monthly picture of the store and writes it to the
`analytics.*` schema. Nothing serves it — the Analytics page is 100% mock. This CAT turns that
buried gold into a read API and a real dashboard, with enough flexibility for an owner to slice
by date, grain, and zone, flip chart types, and export — without pretending the data supports
slices it doesn't._

---

## Agreed product shape (locked)

A **hybrid**: a curated set of widgets, each backed by one clean endpoint, with user-controlled
knobs. NOT a fixed dashboard, NOT a full ad-hoc BI explorer.

User controls:
- **Date range** — presets (Today / 7d / 30d / 90d) + free `from`–`to`.
- **Granularity** — `day | week | month | auto`, exposed as a control. `auto` picks the grain
  from the range span and reads the matching precomputed table.
- **Filters** — which zones (and which employees) to include.
- **View** — line / bar / area is a frontend toggle over the same time-series payload; every
  widget also has a **table view + CSV export**.

Deferred (out of CAT E): arbitrary cross-dimension pivots, user-defined metrics, sub-daily for
arbitrary historical ranges, and natural-language "ask anything" — that last one is the IEP6
agent (CAT G, deferred).

## The data that actually exists (and its limits)

Precomputed by IEP5 (grains: day / week / month unless noted):
- **Store summary** — `total_visits`, `unique_visitors` (customers only, `is_employee=FALSE`),
  `avg`/`median_visit_duration_ms`, `peak_occupancy` (+`_at_ms`, daily only), `dead_period_count`/`_total_ms`.
- **Zone summary** — per zone: `unique_visitors`, `total_transitions`, `avg`/`median_dwell_ms`,
  `max_concurrent`, `passthrough_count`, `engagement_count`, `alert_trigger_count`.
- **Employee summary** — per employee: `scheduled`/`present_duration_ms`, `presence_ratio`,
  `zone_punctuality_delay_ms`, `unassigned_zone_time_ms`.
- **Visit-duration distribution** — histogram buckets (`bucket_label`, `min`/`max_ms`, `count`), daily.
- **Zone sequence matrix** — `from_zone → to_zone`, `transition_count`, `probability`, daily (flow/Sankey).
- **Heatmap** — integer grid cells (`grid_x`, `grid_y`, `hit_count`); hour / day / week / month.

Heavier raw (use sparingly): `visit_sessions`, `zone_transition_log`, `zone_occupancy_15min`
(15-min occupancy cagg), `global_tracking_history` (hypertable).

### ⚠️ The non-additivity rule (the core of "range stitching")

`total_visits` / `transitions` / `passthrough` / `engagement` are **additive** across days.
`unique_visitors`, `avg_*`, `median_*`, `presence_ratio`, `probability` are **NOT** — you cannot
sum or average them across buckets. IEP5 already produced correct weekly/monthly rollups for
exactly this reason. Therefore the API **reads the precomputed table that matches the requested
grain and never re-aggregates non-additive metrics at read time.** Additive counts may be summed
for a range total; non-additive metrics are returned per-bucket (or via the matching week/month
rollup), never fabricated as a single range number.

## Customer vs staff (locked definition)

Store summary visits are customers only. The "Customers vs Staff" composition = customers (from
`daily_store_summary.unique_visitors`) vs **distinct staff present** (from `daily_employee_summary`
rows with `present_duration_ms > 0`, or `visit_sessions WHERE is_employee=TRUE`). Real only when
the store has punch-in linking active (it is live in code; gated on a configured punch station).

## Subpart map

| Spec | Scope | Status |
|---|---|---|
| **E1** [E1-read-api.md](E1-read-api.md) | Analytics router + shared range/grain/filter resolver + rollup-backed endpoints (store-series, zones, composition, distribution, employee, flow-matrix) + empty-state rules. Absorbs old "range stitching" (E2), "classification" (E4), "empty states" (E5). | this CAT, first |
| **E3** [E3-heatmap-projection.md](E3-heatmap-projection.md) | Heatmap endpoint: grid cells → floor-plan pixels (coordinate frame, origin, cell size). Separate — coordinate math. | separate (hard) |
| **E-FE** [E-frontend.md](E-frontend.md) | Wire `Analytics.jsx` to all endpoints; range/grain/zone controls; chart-type toggles; table view + CSV export. | separate |
| **D7** (in CAT D) | Alerts-over-time endpoint, served by this router but reads the `alerts` table → blocked on CAT D. | deferred to D |

## Auth

All endpoints are store-scoped via `get_store_context`; super-admins reach any store via the
[A1](../admin-rbac/A1-authz-core.md) bypass. Read-only — no audit entries.

## Implementation order

E1 → E3 → E-FE. E-FE depends on E1+E3 endpoints existing. D7 lands after CAT D.
