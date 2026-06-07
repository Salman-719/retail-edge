# P1 — Critical Fixes

_Based on direct code reads of agent.proto, orchestrator.py, agent.py, k8s_manager.py,
draft.py, schema.sql, StoreConfigEdit.jsx, api.js._

---

## Fix 1: CAMERA_CONFIG_ID in StartCamera

### Problem (confirmed from code)
`orchestrator.start_camera_workers` (`services/eep/app/core/orchestrator.py:136–192`)
builds a `StartCamera` gRPC message but **does not include `camera_config_id`**, even
though `_LOAD_SQL` (line 29–43) already selects `cc.id AS camera_config_id`.

`agent._build_configmap_data` (`services/edge_agent/app/agent.py:244–264`) writes the
k3s ConfigMap that IEP2 reads as env vars. `CAMERA_CONFIG_ID` is **not in this dict**.

IEP2 `run_daemon` (`services/iep2_vision/runtime.py:735–736`) reads
`settings.camera_config_id` and only loads the projector if it is non-empty. Without
this env var, `FloorProjector._mode` stays `None` and all `floor_x`/`floor_y` values
written to `tracking_history` are `NULL`.

---

### Change A: `proto/agent.proto` — add `camera_config_id` field

**File:** `proto/agent.proto` (canonical source; also synced to `services/eep/proto/agent.proto`)

**Current `StartCamera` message (lines 48–57):**
```protobuf
message StartCamera {
  string   camera_id      = 1;
  string   store_id       = 2;
  string   rtsp_url       = 3;
  float    target_fps     = 4;
  float    window_seconds = 5;
  S3Config s3_config      = 6;
  string   redis_url      = 7;
}
```

**Change:** add field 8:
```protobuf
message StartCamera {
  string   camera_id        = 1;
  string   store_id         = 2;
  string   rtsp_url         = 3;
  float    target_fps       = 4;
  float    window_seconds   = 5;
  S3Config s3_config        = 6;
  string   redis_url        = 7;
  string   camera_config_id = 8;   // ← add this
}
```

**Proto stubs regeneration:**
```bash
bash scripts/generate_protos.sh
# or: make proto
# Regenerates:
#   services/eep/app/grpc_generated/agent_pb2.py
#   services/eep/app/grpc_generated/agent_pb2_grpc.py
#   services/edge_agent/app/grpc_generated/agent_pb2.py
#   services/edge_agent/app/grpc_generated/agent_pb2_grpc.py
```

Stubs are binary-serialized descriptors — do NOT edit pb2.py manually; always
regenerate from the proto source.

---

### Change B: `services/eep/app/core/orchestrator.py` — send `camera_config_id`

**Location:** `start_camera_workers`, line ~153 where `StartCamera` is constructed.

**Current code (lines 151–168):**
```python
ctrl = agent_pb2.ControlMessage(
    start_camera=agent_pb2.StartCamera(
        camera_id=physical_camera_id,
        store_id=store_id,
        rtsp_url=rtsp_url,
        target_fps=target_fps,
        window_seconds=settings.WINDOW_SECONDS,
        redis_url=_REDIS_URL,
        s3_config=agent_pb2.S3Config(
            endpoint_url=_S3_ENDPOINT_URL,
            access_key=_S3_ACCESS_KEY,
            secret_key=_S3_SECRET_KEY,
            bucket=_S3_BUCKET,
        ),
    )
)
```

**Change:** add `camera_config_id=camera_config_id` (the variable `camera_config_id`
is already available in scope — it is the function argument):
```python
ctrl = agent_pb2.ControlMessage(
    start_camera=agent_pb2.StartCamera(
        camera_id=physical_camera_id,
        store_id=store_id,
        rtsp_url=rtsp_url,
        target_fps=target_fps,
        window_seconds=settings.WINDOW_SECONDS,
        redis_url=_REDIS_URL,
        camera_config_id=camera_config_id,    # ← add this
        s3_config=agent_pb2.S3Config(
            endpoint_url=_S3_ENDPOINT_URL,
            access_key=_S3_ACCESS_KEY,
            secret_key=_S3_SECRET_KEY,
            bucket=_S3_BUCKET,
        ),
    )
)
```

---

### Change C: `services/edge_agent/app/agent.py` — write `CAMERA_CONFIG_ID` to ConfigMap

**Location:** `_build_configmap_data` function, lines 244–264.

**Current signature:**
```python
def _build_configmap_data(camera_id, store_id, rtsp_url, target_fps) -> dict:
```

**Change:** add `camera_config_id` parameter and include it in the returned dict:
```python
def _build_configmap_data(
    camera_id: str,
    store_id: str,
    rtsp_url: str,
    target_fps: float,
    camera_config_id: str = "",
) -> dict:
    return {
        "CAMERA_ID":           camera_id,
        "STORE_ID":            store_id,
        "WINDOW_SECONDS":      str(WINDOW_SECONDS),
        "LOCAL_REDIS_URL":     LOCAL_REDIS_URL,
        "SERVER_REDIS_URL":    SERVER_REDIS_URL,
        "DATABASE_URL_SERVER": DATABASE_URL_SERVER,
        "RTSP_URL":            rtsp_url,
        "TARGET_FPS":          str(target_fps),
        "CAMERA_CONFIG_ID":    camera_config_id,   # ← add this
    }
```

**Location:** `_handle_start_camera`, line ~316 where `_build_configmap_data` is called:

**Current call:**
```python
cm_data = _build_configmap_data(camera_id, store_id, cmd.rtsp_url, cmd.target_fps)
```

**Change:**
```python
cm_data = _build_configmap_data(
    camera_id, store_id, cmd.rtsp_url, cmd.target_fps,
    camera_config_id=cmd.camera_config_id,
)
```

**Restoration path** (`_restore_active_cameras`, line ~136): reads ConfigMap data from k3s.
`CAMERA_CONFIG_ID` is already stored in the ConfigMap — restoration will pick it up
automatically because `_restore_active_cameras` reads `data.get("CAMERA_CONFIG_ID", "")`
— no change needed there.

---

### Verification
After deploying:
- IEP2 pod logs should contain: `INFO IEP2 daemon starting  camera=<id>  store=<id> ...`
- `kubectl exec -n retailvision <iep2-pod> -- env | grep CAMERA_CONFIG_ID` returns the UUID
- IEP2 logs contain `INFO Homography loaded  camera_config_id=<uuid>` (or PnP/TPS)
- `tracking_history.floor_x` and `floor_y` are non-NULL

---

## Fix 2: Coordinate System — Metres Everywhere

### Problem (confirmed from code)

Three tables currently store canvas pixel coordinates as if they were world coordinates:

| Table | Column(s) | Current state |
|---|---|---|
| `zones` | `points` JSONB | Canvas pixels |
| `floor_plans` | `boundary_polygon` JSONB | Canvas pixels |
| `camera_configs` | `position_x`, `position_y` FLOAT | Canvas pixels |

`FloorProjector` in IEP2 loads `boundary_polygon` and constructs `Polygon(pts)` directly.
`zone_of(floor_x, floor_y)` checks `polygon.contains(Point(floor_x, floor_y))`. Both
`floor_x`/`floor_y` and the polygon must be in the same coordinate space.

Currently `floor_x`/`floor_y` from the homography is in the space of the "world"
correspondence points — which are also canvas pixels. So the system is internally
consistent but everything is in canvas pixels, not metres.

After this fix:
- All three tables store world metres
- The API always returns canvas pixels to the frontend
- The API always converts canvas pixels → metres before DB write
- `FloorProjector` boundary check is now in metres (consistent with TPS output — see P2)

**Conflict note:** homography calibration still uses canvas pixels as "world" correspondence
points. After this fix, `floor_x`/`floor_y` from homography-calibrated cameras will still
be in canvas pixels, but the boundary polygon and zone points will be in metres.
**Resolution:** Once TPS (Phase 2) is the calibration path, homography is legacy. For any
homography camera, zone lookup and boundary clamping will be unit-mismatched. Document
this and treat homography as a deprecated path that must be migrated to TPS.

---

### Coordinate conversion formulas

**Canvas pixels → world metres (save path):**
```python
world_x = (canvas_px - origin_x) / pixels_per_meter
world_y = (canvas_py - origin_y) / pixels_per_meter
```

**World metres → canvas pixels (read path):**
```python
canvas_px = world_x * pixels_per_meter + origin_x
canvas_py = world_y * pixels_per_meter + origin_y
```

`origin_x`, `origin_y`, `pixels_per_meter` are loaded from `floor_plans` row for the
relevant `(version_id, section_id)`.

**Scale not defined guard:** if `floor_plans.scale_defined = false` (or no floor plan row
exists), reject the save with HTTP 422:
```json
{ "error": "Floor plan scale not defined. Complete step 2 before saving.", "code": "SCALE_NOT_DEFINED" }
```

---

### Helper function to add to `draft.py`

```python
async def _get_floor_plan_scale(
    version_id: uuid.UUID,
    section_id: uuid.UUID,
    db: AsyncSession,
) -> FloorPlan:
    """Load the floor plan for (version_id, section_id) and assert scale_defined.

    Raises HTTP 422 if floor plan is missing or scale not defined.
    """
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == version_id,
            FloorPlan.section_id == section_id,
        )
    )
    fp = fp_result.scalar_one_or_none()
    if not fp or not fp.scale_defined:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Floor plan scale not defined. Complete step 2 before saving.",
                "code": "SCALE_NOT_DEFINED",
            },
        )
    return fp


def _px_to_world(points: list, fp: FloorPlan) -> list:
    """Convert [[px, py], ...] canvas pixels to [[wx, wy], ...] world metres."""
    return [
        [(p[0] - fp.origin_x) / fp.pixels_per_meter,
         (p[1] - fp.origin_y) / fp.pixels_per_meter]
        for p in points
    ]


def _world_to_px(points: list, fp: FloorPlan) -> list:
    """Convert [[wx, wy], ...] world metres to [[px, py], ...] canvas pixels."""
    return [
        [w[0] * fp.pixels_per_meter + fp.origin_x,
         w[1] * fp.pixels_per_meter + fp.origin_y]
        for w in points
    ]
```

---

### Operation A: Zone points

#### Save — `create_zone` (`POST /store/{slug}/draft/sections/{section_id}/zones`)

**File:** `draft.py`, function `create_zone` (currently line ~685).

**What currently happens:** `body.points` (canvas pixels from frontend) stored directly
as `Zone.points`.

**Change:**
1. After the existing `scale_defined` check (currently raises 422 already), load the
   full floor plan to get `origin_x, origin_y, pixels_per_meter`.
2. Convert `body.points` → world metres using `_px_to_world`.
3. Store the world-metres list.

The point-bounds check (`0 <= point[0] <= fp.width_px`) runs BEFORE conversion, on the
raw canvas coords — keep this check as-is.

#### Save — `update_zone` (`PUT /store/{slug}/draft/sections/{section_id}/zones/{zone_id}`)

**File:** `draft.py`, function `update_zone` (currently line ~760).

**Change:** when `body.points is not None`:
1. Load floor plan for the section/version.
2. Run bounds check on raw canvas coords (same as create_zone).
3. Convert `body.points` → world metres using `_px_to_world`.
4. Store the world-metres list.

The overlap check `polygons_overlap(new_points, existing.points)` currently operates on
canvas pixels. After the fix, both `new_points` and `existing.points` are in metres —
the check is still valid (shapely polygons work in any consistent unit).

#### Read — `list_draft_zones` (`GET /store/{slug}/draft/sections/{section_id}/zones`)

**File:** `draft.py`, function `list_draft_zones` (currently line ~671).

**What currently happens:** returns ORM objects directly.

**Change:** after fetching zones, convert `zone.points` world metres → canvas pixels
before returning. Because these are ORM objects (not dicts), create response dicts:

```python
@router.get(...)
async def list_draft_zones(...):
    draft = await _require_draft(ctx.store_id, db)
    result = await db.execute(
        select(Zone).where(Zone.version_id == draft.id, Zone.section_id == section_id)
    )
    zones = result.scalars().all()
    # Need floor plan scale for conversion
    fp = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == section_id,
        )
    )
    fp_row = fp.scalar_one_or_none()
    if fp_row and fp_row.scale_defined:
        return [
            {**{c.key: getattr(z, c.key) for c in z.__table__.columns},
             "points": _world_to_px(z.points, fp_row)}
            for z in zones
        ]
    return zones  # fallback: no scale defined yet, return as-is
```

**Simpler approach:** add a `_zone_response(zone, fp)` helper that builds the response
dict with converted points, and use it in both `list_draft_zones` and `create_zone`
return.

#### DB format
- Stored: `[[world_x_metres, world_y_metres], ...]` (float, may be negative)
- Returned to frontend: `[[canvas_px, canvas_py], ...]` (float, same as what frontend sent)

---

### Operation B: Boundary polygon

#### Save — `set_floor_plan_scale` (`PUT /store/{slug}/draft/sections/{section_id}/floor-plan/scale`)

**File:** `draft.py`, function `set_floor_plan_scale` (currently line ~565).

**What currently happens (line ~600–602):**
```python
if body.boundary_polygon is not None:
    fp.boundary_polygon = body.boundary_polygon if len(body.boundary_polygon) >= 3 else None
```

`body.boundary_polygon` contains canvas pixel coordinates from the frontend.

**Change:** convert to world metres before storing. The scale is computed in this same
function from `body.ref_point_1`, `body.ref_point_2`, `body.real_distance_meters`, and
`body.origin_x/y`. Use these inline values for conversion (don't re-read from DB, since
the floor plan row is being updated):

```python
pixels_per_meter = pixel_distance / body.real_distance_meters

if body.boundary_polygon is not None and len(body.boundary_polygon) >= 3:
    fp.boundary_polygon = [
        [(p[0] - body.origin_x) / pixels_per_meter,
         (p[1] - body.origin_y) / pixels_per_meter]
        for p in body.boundary_polygon
    ]
else:
    fp.boundary_polygon = None
```

#### Read — `get_draft_floor_plan` and `set_floor_plan_scale` responses

**Both** return a `FloorPlanDetailResponse` which includes `boundary_polygon`.

**Change:** convert `fp.boundary_polygon` back to canvas pixels in the response:

```python
def _fp_boundary_to_px(fp: FloorPlan) -> list | None:
    if not fp.boundary_polygon or not fp.scale_defined:
        return fp.boundary_polygon
    return _world_to_px(fp.boundary_polygon, fp)
```

Use in every place that returns `FloorPlanDetailResponse`:
```python
boundary_polygon=_fp_boundary_to_px(fp),
```

This affects:
- `get_draft_floor_plan` response
- `set_floor_plan_scale` response
- `set_floor_plan_boundary_polygon` response (if boundary_polygon is also set there)

Note: `set_floor_plan_boundary_polygon` (`/world-bounds`) currently does NOT touch
`boundary_polygon` — it only sets `world_x_min/max/y_min/max`. No change needed there.

#### DB format
- Stored: `[[world_x_metres, world_y_metres], ...]`
- Returned to frontend: `[[canvas_px, canvas_py], ...]`

---

### Operation C: camera_configs position_x / position_y

#### Save — `place_camera_config` (`POST /store/{slug}/draft/sections/{section_id}/camera-configs`)

**File:** `draft.py`, function `place_camera_config` (currently line ~1142).

**What currently happens:** `body.position_x` and `body.position_y` (canvas pixels) stored
directly into `CameraConfig`.

**Change:**
1. Load floor plan scale for `(draft.id, section_id)`.
2. Convert canvas pixels → world metres.
3. Store world metres.

```python
fp = await _get_floor_plan_scale(draft.id, section_id, db)
cc = CameraConfig(
    version_id=draft.id,
    physical_camera_id=body.physical_camera_id,
    section_id=section_id,
    position_x=(body.position_x - fp.origin_x) / fp.pixels_per_meter,
    position_y=(body.position_y - fp.origin_y) / fp.pixels_per_meter,
    height_meters=body.height_meters,
    fov_deg=body.fov_deg,
)
```

#### Save — `update_camera_config` (`PUT /store/{slug}/draft/camera-configs/{config_id}`)

**File:** `draft.py`, function `update_camera_config` (currently line ~1196).

**Change:** if `position_x` or `position_y` is in `body.model_dump(exclude_none=True)`,
load floor plan scale and convert before `setattr`.

The section_id for the existing config must be used to find the correct floor plan:
```python
fp = await _get_floor_plan_scale(draft.id, cc.section_id, db)
updates = body.model_dump(exclude_none=True)
if "position_x" in updates:
    updates["position_x"] = (updates["position_x"] - fp.origin_x) / fp.pixels_per_meter
if "position_y" in updates:
    updates["position_y"] = (updates["position_y"] - fp.origin_y) / fp.pixels_per_meter
for field, value in updates.items():
    setattr(cc, field, value)
```

Only load fp if position fields are present (avoid unnecessary DB query).

#### Read — `_camera_config_response` helper

**File:** `draft.py`, function `_camera_config_response` (currently line ~98).

Currently returns `CameraConfigResponse` with `position_x=cc.position_x`.

**Change:** add floor plan parameter (or load it inline) and convert world → canvas pixels:

```python
async def _camera_config_response(
    cc: CameraConfig, db: AsyncSession, fp: FloorPlan | None = None
) -> CameraConfigResponse:
    pc_result = await db.execute(...)
    pc = pc_result.scalar_one()
    frame_url = ...

    # Convert position back to canvas pixels for frontend
    if fp and fp.scale_defined:
        pos_x = cc.position_x * fp.pixels_per_meter + fp.origin_x
        pos_y = cc.position_y * fp.pixels_per_meter + fp.origin_y
    else:
        pos_x = cc.position_x
        pos_y = cc.position_y

    return CameraConfigResponse(
        ...
        position_x=pos_x,
        position_y=pos_y,
        ...
    )
```

All callers of `_camera_config_response` must pass the floor plan:
- `list_draft_camera_configs`: load fp once, pass to each call
- `place_camera_config`: pass the fp already loaded for conversion
- `update_camera_config`: load fp, pass it

#### DB format
- Stored: world metres (float, may be fractional, may be negative)
- Returned to frontend: canvas pixels (float)

---

### Existing data
Existing stored data (canvas pixels) becomes invalid. No migration is needed — the spec
says existing data is throwaway. Any existing draft must be discarded and re-created.

---

## Verification Checklist

- [ ] IEP2 logs show `CAMERA_CONFIG_ID` env var on startup (check with `kubectl exec ... env | grep CAMERA_CONFIG_ID`)
- [ ] `tracking_history.floor_x` and `floor_y` are non-NULL after first batch
- [ ] Zone points returned from `GET .../zones` are in canvas pixels (match what was drawn)
- [ ] Zone points in DB (`SELECT points FROM zones`) are in world metres (small floats)
- [ ] Boundary polygon in DB (`SELECT boundary_polygon FROM floor_plans`) is in world metres
- [ ] `camera_configs.position_x/y` in DB are in world metres
- [ ] Saving zones without `scale_defined=true` on the floor plan returns HTTP 422 with `code=SCALE_NOT_DEFINED`
- [ ] Saving camera position without `scale_defined=true` returns HTTP 422
- [ ] Round-trip: place camera at canvas pixel (500, 300) on a floor plan with `origin=(100,50)`, `pixels_per_meter=50` → DB stores `(8.0, 5.0)` → API returns `(500.0, 300.0)`
