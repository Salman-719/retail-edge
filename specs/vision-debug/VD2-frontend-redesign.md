# VD2 — DevE2E Frontend Redesign

_Same data, legible at last. One real floor map as the centerpiece, camera panels collapsed to their
essentials, and a single identity color/number that follows a person from camera to camera to the
reconciled global track. This is the readability win — it needs no new backend._

## Non-obvious tooling / facts

- The page ([DevE2E.jsx](../../frontend/src/pages/DevE2E.jsx)) already loads the active version
  (floor plan, zones, camera_configs) and streams live frames over the bridge ws (detections carry
  `reid_sim`/`reid_matched`). It just never draws the real floor plan — `TrackMap` is a data-fit
  projection on a black box, per camera.
- Each `CameraPanel` currently stacks six sub-sections (feed, save, replay, stats, table, TrackMap,
  FootPointFrame) and renumbers `local_id` with its **own** counter → no cross-camera through-line.
- The shared `worldToPixel` helper (`px = world*ppm + origin`) + `floor_plan` give a real overlay.
- `global_local_mapping` (via a dev read, VD3) maps each `local_id`→`global_id` for coloring.

## Architectural map

```
pages/DevE2E.jsx               restructure into stage regions + shared identity context
components/devE2E/
  ControlBar.jsx               session config (cameras/count/device) | run state (Start/Stop/status)
  UnifiedFloorMap.jsx          real plan + zones + per-camera foot-points + IEP3 global dots
  CameraTile.jsx               compact feed + key stats; details behind an expander
  CameraDetails.jsx            (expander) tracking table + replay scrubber + foot-point snapshot
  IdentityLegend.jsx           color/number key: zones, cameras, globals, matched/pending
lib/identityColors.js          stable color+number per global_id (page-level, not per panel)
lib/floorProjection.js         reuse worldToPixel
```

## Read before implementing

- [DevE2E.jsx](../../frontend/src/pages/DevE2E.jsx) (the whole current page)
- the shared `worldToPixel` ([E-frontend](../analytics/E-frontend.md)); [C1](../store-config/C1-split-view.md) FloorMap for canvas patterns

## Rules (verifiable)

1. **Stage-based layout**: three legible regions — (a) camera feeds (IEP1/2), (b) the **unified floor
   map**, (c) IEP3 output/summary — with a clean sticky `ControlBar` (session config on one side, run
   state + Start/Stop + status on the other). Errors render as a banner/toast, not truncated inline.
2. **Unified floor map (centerpiece)**: render the real floor plan (`display_url`) + zones via
   `worldToPixel`; overlay each camera's IEP2 foot-points (colored per camera) and the IEP3 reconciled
   global dots (colored per global). Layer toggles: per-camera foot-points, IEP3 globals, zones. Click
   a camera to focus/highlight its points. This **replaces** the per-panel data-fit `TrackMap`s.
3. **Progressive disclosure**: `CameraTile` default = live feed + a compact stat line (dets, rows,
   frame, status). The tracking table, replay scrubber, and foot-point snapshot move into a
   `CameraDetails` expander (collapsed by default). At 4–6 cameras, tiles shrink; the map stays primary.
4. **Identity coherence**: a single page-level numberer+palette keyed by `global_id`
   (`lib/identityColors.js`). The SAME color/number marks a person in every camera feed, on the map,
   and in the IEP3 table. Within-camera `local_id`s map to their global via VD3's mapping; show the
   global number on each bbox label (not a per-panel local counter).
5. **Legend**: one `IdentityLegend` (zone colors, camera colors, global numbers, matched✓/pending).
6. **Remove redundancy**: drop the duplicated frame label (keep one), the per-panel TrackMap (replaced
   by the unified map), and the per-panel local numberer (replaced by the shared identity map).
7. **No data/visual regressions**: keep the live feed + bboxes + foot dots + `reid_sim` labels, the
   replay scrubber (in the expander), the save-JPEG, and the IEP3 table — just reorganized.

## Acceptance

- One real floor map shows zones, every camera's foot-points (distinct per camera), and IEP3 global
  dots; toggles hide/show each layer; focusing a camera highlights its points.
- A person crossing from camera 1 to camera 2 keeps the **same** identity color+number across both
  feeds, the map, and the IEP3 table.
- Default screen is clean (feeds + map + summary); tables/replay/snapshots appear only when expanded.
- At 6 cameras the page is navigable (map primary, tiles compact) rather than an endless scroll.
- A foot-point at a known zone renders inside that zone (shared projection — same proof as heatmap/live).

## Hard constraints & anti-patterns

- **Do NOT** keep the data-fit `TrackMap` — the real floor plan + `worldToPixel` is the single map.
- **Do NOT** renumber identity per panel — one page-level identity map, consistent everywhere.
- **Do NOT** show everything at once — default compact, details on demand.
- **Do NOT** add a second projection formula — reuse `worldToPixel`.
- Keep it a dev tool: richness over micro-optimization, but don't hold thousands of frames per camera
  in memory unbounded (the existing 2000-frame cap stays).

## Pinned versions

`react@^18.2.0` · `react-konva@^18.2.10` · `konva@^9.3.2` · `axios@^1.7.2` · `lucide-react@^1.17.0`
— all present, no additions.
