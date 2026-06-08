# S2 — Punch-Station Config API (Draft Wizard)

_Manager designates the punch camera + marks the machine's floor point. Reuses the P1
px↔metres conversion already in `draft.py`. Stored in **world metres**, returned to the
frontend in **canvas pixels**._

## Read before implementing
- [services/eep/app/api/routers/draft.py](../../services/eep/app/api/routers/draft.py)
  — coordinate helpers `_get_floor_plan_scale` (L76), `_px_to_world` (L103),
  `_world_to_px` (L112); camera-config pattern `place_camera_config` (L1232),
  `_camera_config_response` (L153); clone logic `_clone_active_into_draft` (L210).
- [services/eep/app/schemas/draft.py](../../services/eep/app/schemas/draft.py) — request/response model conventions.

## Endpoints (add to `draft.py`, prefix already `/api`)

### `GET /store/{slug}/draft/punch-station`
Return the draft's station (404 `NO_PUNCH_STATION` if none). Convert stored world metres →
canvas px using the floor plan (same pattern as `_camera_config_response`):
```python
pos_x = station.world_x * fp.pixels_per_meter + fp.origin_x
pos_y = station.world_y * fp.pixels_per_meter + fp.origin_y
```
Response: `id, version_id, camera_config_id, position_x, position_y (px), radius_m,
camera_config_name (physical camera name for display)`.

### `PUT /store/{slug}/draft/punch-station`  (upsert)
Body `PunchStationRequest`:
```python
class PunchStationRequest(BaseModel):
    camera_config_id: uuid.UUID
    position_x: float          # canvas px
    position_y: float          # canvas px
    radius_m:   float = 1.5
```
Logic:
1. `_require_draft` + `_require_draft_access`.
2. `fp = await _get_floor_plan_scale(draft.id, ctx.store_id, db)` (422 if scale undefined).
3. Validate `camera_config_id` belongs to this draft version and is placed; recommended:
   require its `status IN ('calibrated','verified')` so the punch camera can actually
   project floor coords. (422 `CAMERA_NOT_IN_DRAFT` / `CAMERA_NOT_CALIBRATED`.)
4. Validate the point is within floor bounds (`0 ≤ position_x ≤ fp.width_px`, same for y) —
   reuse the zone bounds-check error `POINT_OUT_OF_BOUNDS`.
5. Convert px → metres: `world_x, world_y = _px_to_world([[position_x, position_y]], fp)[0]`.
6. Upsert the single row for `version_id` (UNIQUE constraint enforces one); `radius_m > 0`.
7. Return same shape as GET.

### `DELETE /store/{slug}/draft/punch-station` → 204
Remove the draft's station row.

## Schemas (`schemas/draft.py`)
Add `PunchStationRequest`, `PunchStationResponse`. Export from the `__init__`/import block
that `draft.py` already pulls from (see its top-of-file import list).

## Clone into draft
In `_clone_active_into_draft` ([draft.py:210](../../services/eep/app/api/routers/draft.py#L210)),
after camera configs are cloned (their new IDs are known via `new_cc`), copy the active
version's `punch_in_stations` row to the draft, **remapping `camera_config_id`** from the
old config to the newly-cloned config. Build an `old_cc_id → new_cc_id` map while looping
camera configs, then insert the station against the draft `version_id`. If the source
station's camera wasn't cloned (shouldn't happen), skip with a log line.

## Activation
**No orchestrator change.** `activate_version_now`
([orchestrator.py:241](../../services/eep/app/core/orchestrator.py#L241)) only flips version
status; the station row already belongs to the draft version that becomes active. The S4
resolver gates on `store_config_versions.status='active'`.

## Acceptance
- PUT then GET round-trips: px in → stored metres → px out equals input (within float
  epsilon), given a defined scale.
- Deleting/Re-uploading the floor plan cascades (FK `ON DELETE CASCADE` via version) and
  the station is wiped along with zones (verify against the re-upload wipe in
  `upload_floor_plan`, [draft.py:518](../../services/eep/app/api/routers/draft.py#L518) —
  **add `punch_in_stations` to that cascade wipe** since it references camera_configs that
  get deleted there).
- Cloning an active version into a new draft carries the station with a remapped camera.
