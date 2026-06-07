# P2 — TPS Calibration

_Depends on P1 (coordinate system fix) being applied first. All world coordinates
stored/returned by the new endpoints are in metres._

---

## Library Dependency

**Add to `services/eep/requirements.txt`:**
```
scipy==1.13.0
```

`numpy==1.26.4` and `shapely==2.0.4` are already present — do not change.

`scipy.interpolate.RBFInterpolator` requires scipy >= 1.7.0. scipy 1.13.0 satisfies this.

---

## Backend Change 1: Schema

Add `'tps'` to `calibrations.method` CHECK constraint.

**Idempotent SQL (add as Alembic migration `0007_tps_method.py`):**
```sql
ALTER TABLE calibrations DROP CONSTRAINT IF EXISTS calibrations_method_check;
ALTER TABLE calibrations ADD CONSTRAINT calibrations_method_check
    CHECK (method IN ('homography', 'calibration_files', 'pnp', 'tps'));
```

**Conflict note:** `schema.sql` also contains the `calibrations_method_check` constraint
from the M7-S1 migration section at the bottom of the file. Update that block too so
fresh-database setups include `'tps'` from the start.

---

## Backend Change 2: TPS Computation Endpoint

### Route

**New endpoint — keep homography route working, add TPS separately:**

```
POST /store/{slug}/draft/camera-configs/{config_id}/calibration/tps
```

Adding a new route (rather than overloading `/homography`) avoids changing the
`computeHomography` call in the existing frontend path and keeps the homography endpoint
unchanged.

### Request Body Schema (new Pydantic model `TpsCorrespondence` and `TpsRequest`)

```python
class TpsCorrespondence(BaseModel):
    frame_px: float   # pixel X in the camera frame (full resolution)
    frame_py: float   # pixel Y in the camera frame (full resolution)
    map_px:   float   # pixel X on the floor plan canvas (what user clicked)
    map_py:   float   # pixel Y on the floor plan canvas (what user clicked)

class TpsRequest(BaseModel):
    correspondences: list[TpsCorrespondence]
```

### Handler Logic (in `draft.py`)

```python
@router.post(
    "/store/{slug}/draft/camera-configs/{config_id}/calibration/tps",
    response_model=TpsCalibrationResponse,
    status_code=201,
)
async def compute_tps_calibration(
    slug: str,
    config_id: uuid.UUID,
    body: TpsRequest,
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
```

**Step 1: Validate minimum points**
```python
if len(body.correspondences) < 8:
    raise HTTPException(422, {"error": "Minimum 8 correspondences required.", "code": "TOO_FEW_POINTS"})
```

**Step 2: Validate no duplicate frame points**
```python
frame_pts_set = set()
for c in body.correspondences:
    key = (round(c.frame_px, 2), round(c.frame_py, 2))
    if key in frame_pts_set:
        raise HTTPException(422, {"error": "Duplicate frame points detected. Each frame point must be unique.", "code": "DUPLICATE_FRAME_POINTS"})
    frame_pts_set.add(key)
```

**Step 3: Load camera config and floor plan scale**
```python
cc = ...  # load camera config for config_id in draft
fp = await _get_floor_plan_scale(draft.id, cc.section_id, db)
```

**Step 4: Convert map pixels → world metres**
```python
corr_list = []
for c in body.correspondences:
    world_x = (c.map_px - fp.origin_x) / fp.pixels_per_meter
    world_y = (c.map_py - fp.origin_y) / fp.pixels_per_meter
    corr_list.append({
        "frame_px": c.frame_px,
        "frame_py": c.frame_py,
        "map_px":   c.map_px,
        "map_py":   c.map_py,
        "world_x_m": world_x,
        "world_y_m": world_y,
    })
```

**Step 5: Fit TPS interpolators**
```python
import numpy as np
from scipy.interpolate import RBFInterpolator

frame_pts = np.array([[c["frame_px"], c["frame_py"]] for c in corr_list])
world_pts = np.array([[c["world_x_m"], c["world_y_m"]] for c in corr_list])

rbf_x = RBFInterpolator(frame_pts, world_pts[:, 0], kernel='thin_plate_spline', smoothing=0)
rbf_y = RBFInterpolator(frame_pts, world_pts[:, 1], kernel='thin_plate_spline', smoothing=0)
```

**Step 6: Compute coverage score**
```python
from shapely.geometry import MultiPoint

# Load stream resolution from physical_cameras
pc = ...  # load physical_cameras row via cc.physical_camera_id
stream_w = pc.stream_width
stream_h = pc.stream_height

hull = MultiPoint(frame_pts).convex_hull
if stream_w and stream_h and stream_w > 0 and stream_h > 0:
    frame_area = stream_w * stream_h
    coverage_score = float(hull.area / frame_area)
else:
    # Fallback: hull area vs bounding box of frame points
    x_range = float(frame_pts[:, 0].max() - frame_pts[:, 0].min())
    y_range = float(frame_pts[:, 1].max() - frame_pts[:, 1].min())
    bbox_area = x_range * y_range
    coverage_score = float(hull.area / bbox_area) if bbox_area > 0 else 0.0
```

**Step 7: Reject low coverage**
```python
if coverage_score < 0.40:
    raise HTTPException(422, {
        "error": f"Point coverage too low ({coverage_score:.2f}). Spread points across more of the frame.",
        "code": "POOR_COVERAGE",
    })
```

**Step 8: Quality label**
```python
def _tps_quality(coverage: float) -> str:
    if coverage >= 0.70:
        return "excellent"
    return "good"  # >= 0.40 already guaranteed by guard above
```

**Step 9: DB write (single transaction)**
```python
now = datetime.now(timezone.utc)

# Demote prior current calibration
await db.execute(
    update(Calibration)
    .where(Calibration.camera_config_id == config_id, Calibration.is_current == True)
    .values(is_current=False)
)

# Insert new TPS calibration
cal = Calibration(
    camera_config_id=config_id,
    method="tps",
    status="ok",
    is_current=True,
    correspondences=corr_list,   # contains frame_px, frame_py, map_px, map_py, world_x_m, world_y_m
    coverage_score=coverage_score,
    point_count=len(corr_list),
    computed_at=now,
)
db.add(cal)

cc.status = "calibrated"
cc.updated_at = now

await db.commit()
await db.refresh(cal)
```

**Step 10: Redis hot reload signal**
```python
try:
    await redis.publish(f"iep2:reload:{config_id}", "tps")
except Exception as exc:
    logger.warning("Failed to publish tps reload signal config_id=%s: %s", config_id, exc)
```

**Step 11: Response**
```python
return TpsCalibrationResponse(
    calibration_id=cal.id,
    method="tps",
    status="ok",
    coverage_score=coverage_score,
    point_count=len(corr_list),
    quality=_tps_quality(coverage_score),
)
```

### New Pydantic Response Schema

```python
class TpsCalibrationResponse(BaseModel):
    calibration_id: uuid.UUID
    method: str         # always "tps"
    status: str         # always "ok" on success
    coverage_score: float
    point_count: int
    quality: str        # "excellent" | "good"
```

---

## Backend Change 3: Project-Point Endpoint

### Route (already exists — update it)

```
POST /store/{slug}/draft/camera-configs/{config_id}/project-point
```

This endpoint **already exists** in `draft.py` at line ~1556 and handles `homography` and
`pnp` methods by calling `project_pixel_to_world`. It needs to also handle `tps`.

**Conflict:** The spec says "New endpoint" but the endpoint already exists. Resolution:
extend the existing endpoint to handle TPS.

### Updated Logic

**Current code (lines 1596–1612):**
```python
cal_result = await db.execute(...)
cal = cal_result.scalar_one_or_none()
if cal is None: raise HTTPException(...)

world = project_pixel_to_world(
    cal.method, body.frame_px, body.frame_py,
    homography_matrix=cal.homography_matrix,
    ...
)
```

**Change:** add TPS branch before calling `project_pixel_to_world`:

```python
if cal.method == "tps":
    world = _project_tps(cal, body.frame_px, body.frame_py)
else:
    world = project_pixel_to_world(
        cal.method, body.frame_px, body.frame_py,
        homography_matrix=cal.homography_matrix,
        intrinsic_matrix=cal.intrinsic_matrix,
        dist_coeffs=cal.dist_coeffs,
        rotation_vector=cal.rotation_vector,
        translation_vector=cal.translation_vector,
    )
```

**New helper `_project_tps`** (add to `draft.py`):

```python
def _project_tps(
    cal: Calibration,
    frame_px: float,
    frame_py: float,
) -> tuple[float, float] | None:
    """Reconstruct TPS interpolators from stored correspondences and project one point."""
    try:
        import numpy as np
        from scipy.interpolate import RBFInterpolator

        corr = cal.correspondences or []
        if len(corr) < 4:
            return None
        frame_pts = np.array([[c["frame_px"], c["frame_py"]] for c in corr])
        world_pts = np.array([[c["world_x_m"], c["world_y_m"]] for c in corr])

        rbf_x = RBFInterpolator(frame_pts, world_pts[:, 0], kernel='thin_plate_spline', smoothing=0)
        rbf_y = RBFInterpolator(frame_pts, world_pts[:, 1], kernel='thin_plate_spline', smoothing=0)

        query = np.array([[frame_px, frame_py]])
        world_x = float(rbf_x(query)[0])
        world_y = float(rbf_y(query)[0])
        return world_x, world_y
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("TPS projection failed: %s", exc)
        return None
```

### Updated Response

The existing `ProjectPointResponse` schema is:
```python
class ProjectPointResponse(BaseModel):
    method: str
    world_x: float | None
    world_y: float | None
```

**Add `map_px` and `map_py` fields** (canvas pixels, converted from world metres) to
enable the frontend to place a dot on the floor plan canvas without doing coordinate math:

```python
class ProjectPointResponse(BaseModel):
    method: str
    world_x: float | None     # world metres
    world_y: float | None     # world metres
    map_px:  float | None     # canvas pixels (= world_x * ppm + origin_x)
    map_py:  float | None     # canvas pixels
```

**Backend computation of `map_px/map_py`:** load floor plan scale after projection and
convert world metres → canvas pixels. For homography (which may still output "pixel-space
world coords"), omit conversion (set `map_px = world_x`, `map_py = world_y` as before
— the user sees pixel-space numbers, consistent with old behaviour).

```python
if world is None:
    return ProjectPointResponse(method=cal.method, world_x=None, world_y=None, map_px=None, map_py=None)

world_x, world_y = world

# For TPS: convert world metres to canvas pixels for the frontend overlay
map_px, map_py = world_x, world_y  # default (homography pixel-space passthrough)
if cal.method == "tps":
    fp_result = await db.execute(
        select(FloorPlan).where(
            FloorPlan.version_id == draft.id,
            FloorPlan.section_id == cc.section_id,
        )
    )
    fp_row = fp_result.scalar_one_or_none()
    if fp_row and fp_row.scale_defined:
        map_px = world_x * fp_row.pixels_per_meter + fp_row.origin_x
        map_py = world_y * fp_row.pixels_per_meter + fp_row.origin_y

return ProjectPointResponse(
    method=cal.method,
    world_x=world_x,
    world_y=world_y,
    map_px=map_px,
    map_py=map_py,
)
```

---

## IEP2: TPS projection in `FloorProjector`

**File:** `services/iep2_vision/projection/projector.py`

The `_CALIBRATION_SQL` already selects `c.method` and `c.correspondences`. The
`_load_calibration` method already handles unknown methods gracefully (falls through to
`log.warning` and leaves `_mode = None`). TPS needs a new branch.

### Changes to `projector.py`

**Add to `__init__`:**
```python
self._rbf_x = None  # TPS RBFInterpolator for X
self._rbf_y = None  # TPS RBFInterpolator for Y
```

**Add to `_load_calibration` method** (after the `elif method == "homography"` branch):
```python
elif method == "tps":
    try:
        import numpy as np
        from scipy.interpolate import RBFInterpolator

        corr = json.loads(row["correspondences"]) if isinstance(row["correspondences"], str) else row["correspondences"]
        if not corr or len(corr) < 4:
            log.warning("TPS calibration has too few control points  camera_config_id=%s", self._camera_config_id)
            return

        frame_pts = np.array([[c["frame_px"], c["frame_py"]] for c in corr])
        world_pts = np.array([[c["world_x_m"], c["world_y_m"]] for c in corr])

        self._rbf_x = RBFInterpolator(frame_pts, world_pts[:, 0], kernel='thin_plate_spline', smoothing=0)
        self._rbf_y = RBFInterpolator(frame_pts, world_pts[:, 1], kernel='thin_plate_spline', smoothing=0)
        self._mode = "tps"
        log.info("TPS calibration loaded  camera_config_id=%s  control_points=%d",
                 self._camera_config_id, len(corr))
    except Exception as exc:
        log.error("Failed to load TPS calibration  camera_config_id=%s: %s", self._camera_config_id, exc)
        self._mode = None
```

**Add to `_load_calibration` reset block** (clear TPS state on reload):
```python
self._rbf_x = None
self._rbf_y = None
```

**Add TPS branch to `_project_foot`:**
```python
if self._mode == "tps":
    return self._project_tps(u, v)
```

**New method `_project_tps`:**
```python
def _project_tps(self, u: float, v: float) -> tuple[float, float] | None:
    """Project via TPS interpolators. Returns (world_x_m, world_y_m) or None."""
    try:
        import numpy as np
        query = np.array([[u, v]])
        world_x = float(self._rbf_x(query)[0])
        world_y = float(self._rbf_y(query)[0])
        return world_x, world_y
    except Exception as exc:
        log.warning("TPS projection failed  camera_config_id=%s: %s", self._camera_config_id, exc)
        return None
```

**`_CALIBRATION_SQL` change:** add `c.correspondences` to the SELECT (if not already present):

Currently selected columns: `c.method, c.homography_matrix, c.intrinsic_matrix, c.dist_coeffs, c.rotation_vector, c.translation_vector`.

Add: `, c.correspondences`.

---

## IEP2: `requirements.txt`

**File:** `services/iep2_vision/requirements.txt`

Add:
```
scipy==1.13.0
```

---

## Frontend Changes

### `frontend/src/api.js`

**Add TPS calibration call:**
```javascript
// TPS calibration — correspondences: [{ frame_px, frame_py, map_px, map_py }]
export const computeTps = (slug, configId, correspondences) =>
  api.post(`/store/${slug}/draft/camera-configs/${configId}/calibration/tps`, { correspondences }).then(r => r.data)
```

**Update `projectPoint` to use returned `map_px/map_py`:**
The existing function signature is unchanged; the backend now returns `map_px, map_py`
fields in addition to `world_x, world_y`. Frontend reads `res.map_px, res.map_py` to
place the dot on the floor plan canvas.

---

### `frontend/src/pages/StoreConfigEdit.jsx`

#### Step 5 — Correspondences (minimal change)

**Current state (confirmed from code):**
- User clicks frame → `pendingPixelPt` set
- User clicks floor plan → correspondence stored as `{ pixel: [px,py], world: [wx,wy] }`
- Points shown on both canvases
- Delete button per row in list

**Change:** The correspondence format sent to the TPS endpoint uses `map_px/map_py`
(the floor plan canvas click), not `world` (which is the same value but named differently).
No UI change needed for collection — only the compute step changes.

**Enforce 8-point minimum in UI:** `isStepComplete(5)` already checks `>= 8` — no change.

---

#### Step 6 — Compute Calibration (replaces Compute Homography)

**Current step label in `STEPS` constant:**
```javascript
{ n: 6, label: 'Compute Homography' },
```
**Change to:**
```javascript
{ n: 6, label: 'Compute Calibration' },
```

**Current handler `handleComputeHomographyFor` (line ~856):**
```javascript
const result = await computeHomography(slug, configId, corr)
```

**Change:** call `computeTps` instead. The `corr` array has items `{ pixel: [frame_px, frame_py], world: [map_px, map_py] }`. Map to TPS format:
```javascript
async function handleComputeCalibrationFor(configId) {
  const corr = correspondencesMap[configId] || []
  if (corr.length < 8) return
  setSaving(true)
  try {
    const tpsCorr = corr.map(c => ({
      frame_px: c.pixel[0],
      frame_py: c.pixel[1],
      map_px:   c.world[0],   // floor plan canvas X
      map_py:   c.world[1],   // floor plan canvas Y
    }))
    const result = await computeTps(slug, configId, tpsCorr)
    setCalibResultsMap(prev => ({ ...prev, [configId]: result }))
    setCameraConfigs(prev => prev.map(c =>
      c.id === configId ? { ...c, status: 'calibrated' } : c
    ))
  } catch (err) {
    setError(err?.response?.data?.error || err.message)
  } finally {
    setSaving(false)
  }
}
```

Rename `handleComputeHomographyFor` → `handleComputeCalibrationFor` throughout.
Update the button `onClick` in step 6 JSX to call `handleComputeCalibrationFor`.

**Result display in step 6:** replace the homography metrics display:

Current display shows: `RMS Error`, `Max Error`, `Coverage`, `Condition #`.

TPS response fields: `coverage_score`, `quality`, `point_count`.

**New display:**
```jsx
{calib && (
  <div className="grid grid-cols-2 gap-1.5 text-xs text-gray-600 bg-gray-50 rounded p-3">
    <span>Coverage</span>
    <span className={`font-mono font-medium ${
      calib.quality === 'excellent' ? 'text-green-600' : 'text-yellow-600'
    }`}>{((calib.coverage_score || 0) * 100).toFixed(1)}%</span>
    <span>Quality</span>
    <span className={`font-mono font-medium ${
      calib.quality === 'excellent' ? 'text-green-600' : 'text-yellow-600'
    }`}>{calib.quality}</span>
    <span>Points</span>
    <span className="font-mono">{calib.point_count}</span>
  </div>
)}
```

**Add recompute button:** when camera is already `calibrated` or `verified` and user
navigates back to step 6, show the recompute button unconditionally (not just when
`!alreadyDone`). The button calls `handleComputeCalibrationFor` to produce a new
calibration row (old one is demoted server-side).

```jsx
<button
  onClick={() => handleComputeCalibrationFor(cc.id)}
  disabled={corr.length < 8 || saving}
  className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
>
  {saving ? 'Computing…' : alreadyDone ? `Recompute (${corr.length} pairs)` : `Compute (${corr.length} pairs)`}
</button>
```

---

#### Step 7 — Verify Calibration

**Current state (confirmed from code):**
- User clicks frame → calls `projectPoint` backend → `verifyPreviewMap` stores `{ pixel, world }`
- `world` point is rendered as a numbered orange dot on floor plan canvas via
  `correspondencePoints={verifyPreview?.world && !correctionMode ? [verifyPreview.world] : []}`
- User can add a correction point (adds to correspondences + re-runs homography)
- `Looks Good` button verifies

**Change required for TPS:**

1. **Use `map_px, map_py` instead of `world` for the canvas overlay.** After TPS, the
   `project-point` response includes `map_px, map_py` (canvas pixels). Store these in
   `verifyPreviewMap`:

   ```javascript
   async function handleFrameClickForVerify(x, y) {
     if (!selectedConfigId) return
     const configId = selectedConfigId
     setVerifyPreviewMap(prev => ({ ...prev, [configId]: { pixel: [x, y], mapPt: null } }))
     try {
       const res = await projectPoint(slug, configId, x, y)
       const mapPt = (res.map_px != null && res.map_py != null) ? [res.map_px, res.map_py] : null
       setVerifyPreviewMap(prev => ({ ...prev, [configId]: { pixel: [x, y], mapPt } }))
     } catch (err) {
       setError(err?.response?.data?.error || err.message)
     }
   }
   ```

2. **Multiple simultaneous test points:** instead of replacing the single preview on each
   click, accumulate them in an array. Add a "Clear test points" button.

   **State change:** replace `verifyPreviewMap[configId]` (single `{pixel, mapPt}`) with
   an array `verifyPreviewMap[configId] = [{ pixel, mapPt }, ...]`.

   **Handler:**
   ```javascript
   async function handleFrameClickForVerify(x, y) {
     if (!selectedConfigId) return
     const configId = selectedConfigId
     // Add pending entry immediately
     setVerifyPreviewMap(prev => ({
       ...prev,
       [configId]: [...(prev[configId] || []), { pixel: [x, y], mapPt: null }],
     }))
     try {
       const res = await projectPoint(slug, configId, x, y)
       const mapPt = (res.map_px != null && res.map_py != null) ? [res.map_px, res.map_py] : null
       // Resolve the pending entry: find the matching unresolved pixel click
       setVerifyPreviewMap(prev => {
         const pts = (prev[configId] || []).slice()
         const idx = pts.findLastIndex(p => p.pixel[0] === x && p.pixel[1] === y && p.mapPt === null)
         if (idx >= 0) pts[idx] = { pixel: [x, y], mapPt }
         return { ...prev, [configId]: pts }
       })
     } catch (err) {
       setError(err?.response?.data?.error || err.message)
     }
   }
   ```

3. **Floor plan overlay:** pass all resolved `mapPt` values to `FloorPlanStage.correspondencePoints`:
   ```javascript
   const verifyPoints = selectedConfigId
     ? (verifyPreviewMap[selectedConfigId] || []).filter(p => p.mapPt).map(p => p.mapPt)
     : []
   // ...
   correspondencePoints={verifyPoints}
   ```

4. **Clear button:**
   ```jsx
   <button onClick={() => setVerifyPreviewMap(prev => ({ ...prev, [selectedConfigId]: [] }))}>
     Clear test points
   </button>
   ```

5. **Remove "Correct Point" interaction from step 7.** If user wants to fix calibration,
   they go back to step 5. Remove `correctionMode`, `correctionPixel`,
   `handleFrameClickForCorrection`, `handleMapClickForCorrection`, and the
   "Correct Point" button from step 7 JSX. Remove those state variables entirely
   (they are only used in step 7).

   Current code that implements correction:
   - State: `correctionMode`, `correctionPixel` (lines ~487–488)
   - Handler: `handleFrameClickForCorrection` (lines ~906–908), `handleMapClickForCorrection`
     (lines ~910–927)
   - JSX: `correctionMode` conditional banner (lines ~1779–1787), "Correct Point" button
     (lines ~1836–1844)
   
   All of this is removed. Step 7 becomes purely a verification preview — click frame,
   see dot on map, decide pass/fail.

---

## Verification Checklist

- [ ] `POST .../calibration/tps` returns 422 for fewer than 8 correspondences (code: `TOO_FEW_POINTS`)
- [ ] `POST .../calibration/tps` returns 422 for coverage_score < 0.40 (code: `POOR_COVERAGE`)
- [ ] `POST .../calibration/tps` returns 422 for duplicate frame points (code: `DUPLICATE_FRAME_POINTS`)
- [ ] Step 6 UI shows coverage score as percentage and quality label
- [ ] Quality `excellent` renders green; quality `good` renders yellow
- [ ] `POST .../project-point` returns `map_px, map_py` in canvas pixel coords for TPS cameras
- [ ] Step 7 renders a numbered dot on the floor plan canvas at `map_px, map_py` after clicking frame
- [ ] Multiple test points can be placed simultaneously; "Clear" removes all
- [ ] "Correct Point" button is gone from step 7
- [ ] "Compute Calibration" button is visible in step 6 even when camera is already calibrated (recompute path)
- [ ] Recomputing TPS produces a new `calibrations` row with `is_current=TRUE`; old row has `is_current=FALSE`
- [ ] Redis signal `'tps'` is published after successful TPS computation (`iep2:reload:{config_id}`)
- [ ] IEP2 `FloorProjector` loads TPS calibration and `_mode = 'tps'`
- [ ] IEP2 logs show `TPS calibration loaded  camera_config_id=...  control_points=N`
- [ ] `tracking_history.floor_x/floor_y` are in metres (small floats) for TPS cameras
- [ ] Homography path still works — `POST .../calibration/homography` unchanged, existing calibrated cameras unaffected
- [ ] `scipy` available in EEP and IEP2 Docker images (`python -c "from scipy.interpolate import RBFInterpolator"`)
