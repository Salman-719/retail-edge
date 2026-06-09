# E3 — Heatmap Endpoint (grid cells → floor-plan overlay)

_The heatmap is the one analytics output that lives in space, not just time. IEP5 stored it as
integer grid cells; to mean anything it must land on the floor plan exactly where people stood.
The trick is to not invent a second coordinate convention: the backend reconstructs each cell's
world rectangle (unambiguous), hands back the floor-plan projection metadata, and the frontend
draws cells with the very same world→pixel transform it already uses for zones._

## Why this is its own spec

Unlike the E1 rollups (read a table, return rows), the heatmap requires turning
`(grid_x, grid_y)` back into world metres and then onto image pixels. Two hazards:
1. **Cell size is not stored per row.** IEP5 computed `grid_x = floor((floor_x - origin_x)/cell_size_m)`
   ([heatmap.py:14](../../services/iep5_analytics/app/aggregators/heatmap.py#L14)) using
   `HEATMAP_CELL_SIZE_M` (default `0.5`) passed in by EEP's `iep5_manager`
   ([iep5_manager.py:25,76](../../services/eep/app/core/iep5_manager.py#L25)). The reader MUST use
   the identical value or every cell is the wrong size.
2. **The world→pixel convention must match how zones/cameras are already drawn** — not a fresh
   formula. The floor-plan projection fields live on `floor_plans`
   ([floor_plan.py:23-34](../../services/eep/app/models/floor_plan.py#L23)):
   `origin_x/y`, `pixels_per_meter`, `world_x/y_min/max`, `width/height_px`, `display_s3_key`.

## Non-obvious tooling / facts

- Heatmap tables ([0010](../../services/eep/alembic/versions/0010_analytics_foundation.py#L411)):
  `heatmap_hourly`/`heatmap_daily` carry `version_id`; `heatmap_weekly`/`heatmap_monthly` do **not**.
  Cells are additive `hit_count` per `(grid_x, grid_y)`.
- The cell's world rectangle is unambiguous from IEP5's formula:
  `world_x_min = origin_x + grid_x*cell`, `world_x_max = +cell` (same for y), with `origin_x` =
  the floor plan's `origin_x` IEP5 used and `cell` = `HEATMAP_CELL_SIZE_M`.
- The active-version endpoint already presigns `display_s3_key` → `display_url` (Analytics.jsx reads
  `v.floor_plan.display_url`). Reuse that S3 presign helper; do not roll a new one.
- EEP's `iep5_manager` reads `HEATMAP_CELL_SIZE_M` straight from `os.environ`. Promote it to
  `core/config.Settings` so the launcher AND this endpoint read **one** source.

## Architectural map

```
core/config.py        (+) HEATMAP_CELL_SIZE_M: float = 0.5   (single source)
core/iep5_manager.py  (~) read settings.HEATMAP_CELL_SIZE_M  (was os.environ)
api/routers/analytics.py  (+) GET /store/{slug}/analytics/heatmap
schemas/analytics.py      (+) HeatmapResponse { floor_plan meta, cell_size_m, max_hit_count, cells[] }
                              reuse floor_plan query + S3 presign
```

## Read before implementing (verify the convention — do NOT assume)

- [aggregators/heatmap.py](../../services/iep5_analytics/app/aggregators/heatmap.py) (how grid was built)
- [models/floor_plan.py](../../services/eep/app/models/floor_plan.py) (projection fields)
- The existing **zone rendering** on the floor plan (Konva editor in
  [StoreConfigEdit.jsx](../../frontend/src/pages/StoreConfigEdit.jsx)) and the active-version
  endpoint that presigns `display_url` — this is the authoritative world↔pixel convention to reuse.
- Confirm the unit of `floor_plan.origin_x` (pixels vs metres) and how `floor_x/floor_y` are
  produced (homography/calibration) before finalizing the cell-rectangle math. If reality differs
  from this spec, report it before coding.

## Rules (verifiable)

1. **Single cell-size source**: add `HEATMAP_CELL_SIZE_M: float = 0.5` to `Settings`; refactor
   `iep5_manager` to read it from `settings`. The endpoint reads the same `settings` value.
2. **`GET /store/{slug}/analytics/heatmap`** `?from&to&granularity=day|hour|week|month` (default
   `day`):
   - Select the heatmap table for the grain; sum `hit_count` per `(grid_x, grid_y)` across all
     buckets in `[from, to]` (counts are additive — correct to sum).
   - `version_id` for the projection: for `hour`/`day`, use the version of the rows (if a range
     spans versions, prefer the store's **active** version and note it in the response); for
     `week`/`month` (no `version_id`), use the active version's floor plan.
3. **Cell → world rectangle** on the backend: `world_x_min = origin_x + grid_x*cell`,
   `world_x_max = world_x_min + cell` (same for y), using the chosen version's `floor_plan.origin_x/y`
   and `settings.HEATMAP_CELL_SIZE_M`. Return these world rects per cell.
4. **Projection metadata** in the response (so the frontend projects identically to zones):
   `floor_plan: { origin_x, origin_y, pixels_per_meter, world_x_min, world_x_max, world_y_min,
   world_y_max, width_px, height_px, display_url, image_uploaded }` plus top-level `cell_size_m`,
   `version_id`, `max_hit_count`.
5. **Normalized intensity**: include `intensity = hit_count / max_hit_count` (0..1) per cell so the
   frontend's existing `heatColor` works without a second pass; also return raw `hit_count`.
6. **Projection stays in the frontend.** The backend returns world rects + metadata; the frontend
   converts world→pixel with the SAME helper it uses for zones/cameras. E3 must NOT introduce a
   second world→pixel formula on either side.
7. **Empty states**: if the active floor plan has `image_uploaded=false`, return the `floor_plan`
   meta with `cells: []` (frontend shows "heatmap needs a configured floor plan"). If the plan
   exists but the range has no cells, return `200` with `cells: []`.

## Acceptance (verify at end of phase)

- **Alignment test (the important one):** pick a zone with known world polygon; request the heatmap;
  a cell whose world rect center falls inside that polygon must render (after frontend projection)
  visually inside the drawn zone. This proves E3 reuses the zone convention rather than a new one.
- Summing a 7-day range yields, per cell, the sum of the 7 daily `hit_count`s (spot-check one cell).
- `granularity=hour` over a single day returns intraday cells; `week`/`month` read the rollup tables.
- Changing `HEATMAP_CELL_SIZE_M` changes returned `world_*` rect sizes consistently (and is read
  from one place).
- A store with no uploaded floor plan returns metadata + empty cells, not a 500.

## Hard constraints & anti-patterns

- **NEVER** hardcode `cell_size_m = 0.5` in the endpoint — read `settings`, the same value the
  writer used. Mismatched cell size silently distorts the whole map.
- **NEVER** invent a world→pixel formula here; reuse the zone/camera projection. Two conventions =
  guaranteed drift.
- **Do NOT** average across cells or normalize per-bucket then re-sum — sum raw counts, normalize once.
- **Do NOT** presume `weekly/monthly` heatmaps carry a version; they don't — use the active version
  and surface `version_id` so the client knows which frame it's projected in.

## Known limitation (acceptable for v1; note in PR)

`HEATMAP_CELL_SIZE_M` and `origin` are not persisted per heatmap row. If an operator changes the
cell size or re-scales the floor plan after data exists, historical heatmaps reproject incorrectly.
**Follow-up (not this spec):** persist `cell_size_m` (and origin) on `floor_plans` per version,
written at activation and consumed by both IEP5 and this endpoint.

## Pinned versions

Python 3.11 · PostgreSQL 16 + TimescaleDB · `fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` ·
`asyncpg==0.29.0` · `boto3` (existing S3 client) · Pydantic v2.
