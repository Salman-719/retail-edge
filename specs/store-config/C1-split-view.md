# C1 — Store Setup Split View (read-only)

_Everything about the store on one screen: the floor map with every zone, camera, obstacle and the
punch machine, alongside detail panels for cameras, zones, schedule, and punch — plus live camera
status so setup and reality are visible together. Read-only; edits go through the C3 menu._

## Non-obvious tooling / facts

- The current view already renders the floor plan + zones + cameras + obstacles on a Konva canvas
  and lists zones/cameras ([StoreConfig.jsx](../../frontend/src/pages/StoreConfig.jsx)). C1 enriches
  it; it does not start from scratch.
- Camera/zone/floor data come from `getActiveVersion` (already loaded). Live status comes from
  **F2** `GET /cameras/health`; per-zone alert-rule counts from **CAT D** `listAlertRules`. Both are
  optional — degrade gracefully if absent.
- Operating hours come from **C2** `GET /operating-hours`; the punch station from **S2**
  (active version's punch station — add a read if only the draft variant exists, see Rule 6).
- Zone **area** = polygon area (shoelace) in px² ÷ `pixels_per_meter²` → m².
- Map projection (punch marker, world points) uses the shared `worldToPixel` (`px = world*ppm +
  origin`).

## Architectural map

```
pages/StoreSetup.jsx        compose the panels (read-only)
components/store/
  CamerasPanel.jsx          per-camera: name, status, height, stream, position, calibration, fps,
                            + LIVE dot (F2)
  ZonesPanel.jsx            per-zone: name, type, area m², alert-rule count (D)
  SchedulePanel.jsx         7-day operating hours (C2) read-only
  PunchPanel.jsx            punch camera + radius (+ "not set" state)
  FloorMap.jsx              zoom/pan + layer toggles; zones/cameras/obstacles/punch marker
  VersionHistory.jsx        collapsible (existing restore logic)
api.js                      + getCameraHealth, getOperatingHours, getActivePunchStation, listAlertRules
```

## Read before implementing

- [StoreConfig.jsx](../../frontend/src/pages/StoreConfig.jsx) (existing canvas + lists to refactor)
- [F2-camera-health.md](../live-monitoring/F2-camera-health.md), [C2-store-operating-hours.md](C2-store-operating-hours.md), [S2](../employee-linking/S2-station-config-api.md)
- the shared `worldToPixel` helper ([E-frontend](../analytics/E-frontend.md))

## Rules (verifiable)

1. **Layout**: 2D map as centerpiece; left column Cameras + Zones (each row expandable to detail);
   Schedule + Punch panels below/beside; collapsible Version History. One scrollable screen.
2. **Cameras panel**: per camera show `name, status (verified/calibrated/...), height_m, stream_url,
   position, calibration status, target_fps`, and a **live online/offline dot** from F2 (`unknown`
   if no report; omit the dot entirely if F2 unavailable). No edit controls.
3. **Zones panel**: per zone show `name, type, area_m²` (computed) and the **count of alert rules**
   targeting it (from D; omit if D absent). No edit controls.
4. **Schedule panel**: render the 7-day operating hours (C2) read-only (open/close per day, "Closed"
   days); a hint to "Edit Schedule" via the C3 menu.
5. **Punch panel**: show the configured punch camera + `radius_m`; if none, a "Punch machine not
   configured" empty state pointing to "Edit Punch Machine".
6. **Punch read source**: if only the **draft** punch endpoint exists (S2), add a read for the
   **active** version's punch station (mirror S2's GET against `status='active'`) so the view can
   show it without a draft. Convert world→px with the shared helper.
7. **Floor map**: zoom + pan; layer toggles for zones / cameras / obstacles / punch; render the
   punch machine as a point + a radius circle (radius_m × ppm). Reuse the shared `worldToPixel`.
8. **Read-only throughout**: no inline edits anywhere (C3). Loading→skeletons; empty states for each
   panel; degrade gracefully when an optional dependency (F2/D) is missing.

## Acceptance

- The map shows zones, cameras, obstacles, and the punch marker+radius; toggles hide/show each layer;
  zoom/pan work.
- Each camera row shows its config detail + a live status dot that matches F2; each zone row shows a
  correct area (m²) and its alert-rule count.
- The schedule panel matches `GET /operating-hours`; the punch panel matches the active punch station
  (or shows the not-configured state).
- With F2 or D unavailable, the page still renders (no live dot / no rule count) without errors.
- Nothing on the page mutates config.

## Hard constraints & anti-patterns

- **Do NOT** add edit controls — all edits route through the C3 menu (versioning).
- **Do NOT** introduce a second world→pixel formula — reuse the shared helper (`px = world*ppm+origin`).
- **Do NOT** hard-fail when F2/D/S2-active are missing — degrade gracefully.
- **Do NOT** recompute zone area on the server — it's a cheap client calc from the polygon + ppm.

## Pinned versions

`react@^18.2.0` · `react-konva@^18.2.10` · `konva@^9.3.2` · `lucide-react@^1.17.0` · `axios@^1.7.2`
— all present, no additions.
