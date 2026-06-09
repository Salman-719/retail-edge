# D7 — Alerts Over Time

_The Alerts page answers "what's wrong now." Analytics should answer "are we getting better."
A simple counts-by-bucket-and-type series turns the alert history into a trend the owner can watch._

## Non-obvious tooling / facts

- Alert counts are **additive** across days — safe to bucket and sum (unlike the E1 uniques).
- This endpoint reads the `alerts` table; it lives in the **alerts** router (cohesive with alerts)
  but renders as a widget on the **Analytics** page (E-frontend pattern + control bar).
- It depends on D3's `severity` column and the D1/D2 read model existing.

## Architectural map

```
api/routers/alerts.py  (+) GET /store/{slug}/alerts/timeseries ?from&to&granularity
schemas/alert.py       (+) AlertTimeseriesRow { bucket_start, type, severity, count }
frontend                  new widget on Analytics page (slots into the shared control bar)
```

## Read before implementing

- [E1-read-api.md](../analytics/E1-read-api.md) (the grain resolver + envelope to match)
- [schema.sql:390-405](../../services/eep/schema.sql#L390) (`alerts.created_at`, `type`, `severity`)

## Rules (verifiable)

1. **`GET /store/{slug}/alerts/timeseries`** `?from&to&granularity=day|week|month|auto` → bucket the
   `alerts` rows by `created_at` (store-local date) at the resolved grain, grouping by `type` and
   `severity`, returning `{ bucket_start, type, severity, count }`. Reuse the E1 grain resolver
   (`core/analytics_grains.py`) so the control behaves identically to the other widgets.
2. Counts include both auto-resolved and manually-dismissed alerts (a fired alert counts regardless
   of how it ended). Optionally accept `?resolution=` to filter.
3. Use the same `{ store_id, grain, from, to, rows }` envelope as the analytics endpoints.
4. Empty range → `200 { rows: [] }` (never 404 / zero-fill missing buckets).
5. Reads gate: any store member (`get_store_context`, admin via A1). Read-only, no audit.

## Acceptance

- `?granularity=day` over a week returns per-day, per-type counts matching a hand count of the
  `alerts` rows in that window.
- `auto` resolves grain by span exactly as the analytics widgets do.
- The Analytics widget renders it as a stacked bar/line by type, honoring the shared range/grain bar.

## Hard constraints & anti-patterns

- **Do NOT** re-implement grain resolution — import E1's resolver (one source).
- **Do NOT** zero-fill empty buckets — omit them (consistent with E1).
- **Do NOT** put this read in the analytics router just because it renders there — it reads `alerts`,
  so it stays in the alerts router.

## Pinned versions

`fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · `recharts@^3.8.1` (widget).
