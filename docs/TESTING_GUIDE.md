# RetailVision — Testing Guide
## Phases 3–6: Business Data, Pipeline Validation, End-to-End, Accuracy

> **Prerequisite:** All items in `INFRA_TESTS.md` Phase 2 Summary Checklist must
> be ✓ before starting this guide. In particular: PostgreSQL, PgBouncer, Redis,
> MinIO, EEP, YOLO, OSNet, and IEP1 must all be healthy.
>
> **Philosophy:** Store configuration is created through the UI wherever
> possible, exactly as a real customer would do it. API and database
> verification commands follow each UI step to confirm data integrity.
>
> **Platform notation:** Same as `INFRA_TESTS.md` — `[WIN]`, `[LIN]`, `[ORIN]`,
> `[BOTH]`. Set `$COMPOSE` alias before starting (see `INFRA_TESTS.md` §Notation).

---

## Test Session Variables

Every ID captured during this guide must be recorded here before proceeding.
Subsequent phases depend on these exact values.

```
STORE_SLUG=           # URL slug (e.g. "acme-flagship")
STORE_ID=             # UUID from stores table (e.g. "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
SECTION_ID=           # UUID of the primary section (one section per store in basic setup)
VERSION_DRAFT_ID=     # UUID of the draft store_config_version
VERSION_ACTIVE_ID=    # UUID of the activated store_config_version
CAMERA_ID_1=          # UUID of physical camera 1
CAMERA_ID_2=          # UUID of physical camera 2 (if multi-camera test)
CAMERA_CONFIG_ID_1=   # UUID of camera_config for camera 1
CAMERA_CONFIG_ID_2=   # UUID of camera_config for camera 2
CALIBRATION_ID_1=     # UUID of the accepted calibration for camera 1
CALIBRATION_ID_2=     # UUID of the accepted calibration for camera 2
JWT_TOKEN=            # Bearer token for API verification commands
```

> **Tip:** Keep a scratch text file open and fill in each variable as you
> complete the step that produces it. Commands below reference these
> variables by name.

---

## Phase 3 — Business Data Creation

### Overview

This phase follows the exact customer onboarding journey. Every step is
performed through the web UI at `http://localhost:3000`. Each UI step is
followed by a verification command that queries the API or database directly
to confirm the data was written correctly.

The complete sequence:

```
Register account
  └─► Create store
        └─► Create section
              └─► Create draft version
                    ├─► Upload floor plan → set scale → set world bounds
                    ├─► Create zones
                    ├─► Register physical cameras
                    ├─► Place cameras on floor plan (camera configs)
                    │     └─► Upload calibration frame
                    │     └─► Compute homography (≥ 4 point pairs)
                    │     └─► Verify calibration
                    └─► Activate draft
```

---

### 3.1 Account Registration

**UI action:** Open `http://localhost:3000`. You should be redirected to
`/register`. Fill in:

| Field | Value |
|---|---|
| Email | your test email address |
| Password | choose a strong password |
| Full name | test tester (or real name) |

Click **Register**. You should be redirected to the owner dashboard.

**API verification:**

**[WIN]**
```powershell
# Verify user exists in DB
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT id, email, created_at FROM users ORDER BY created_at DESC LIMIT 3;
"
```

**[LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c \
  "SELECT id, email, created_at FROM users ORDER BY created_at DESC LIMIT 3;"
```

**Login and capture JWT token** (needed for API verification commands):

**[WIN]**
```powershell
$resp = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/login" `
    -Method POST -ContentType "application/json" `
    -Body '{"email":"YOUR_EMAIL","password":"YOUR_PASSWORD"}'
$JWT_TOKEN = $resp.access_token
"JWT_TOKEN=$JWT_TOKEN"   # Record this value
```

**[LIN/ORIN]**
```bash
resp=$(curl -sf -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"YOUR_EMAIL","password":"YOUR_PASSWORD"}')
JWT_TOKEN=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "JWT_TOKEN=$JWT_TOKEN"
```

---

### 3.2 Store Creation

**UI action:** On the owner dashboard, click **Create Store**. Fill in:

| Field | Guidance |
|---|---|
| Store name | Real store name (e.g. "Acme Flagship") |
| Slug | URL-friendly name (e.g. "acme-flagship"). This becomes `STORE_SLUG`. |
| Address | Real address |
| Timezone | Store's local timezone |

Click **Create**. You should be redirected to `/store/{slug}/config`.

**Capture `STORE_SLUG` and `STORE_ID`:**

**[WIN]**
```powershell
$STORE_SLUG = "acme-flagship"   # replace with your actual slug
$resp = Invoke-RestMethod -Uri "http://localhost:8000/api/store/$STORE_SLUG" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$STORE_ID = $resp.id
"STORE_ID=$STORE_ID"   # Record this UUID
```

**[LIN/ORIN]**
```bash
STORE_SLUG="acme-flagship"   # replace with your actual slug
STORE_ID=$(curl -sf http://localhost:8000/api/store/$STORE_SLUG \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "STORE_ID=$STORE_ID"
```

**DB verification:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c \
  "SELECT id, name, slug, created_at FROM stores WHERE slug='$STORE_SLUG';"
# Expected: 1 row with the correct store name and slug
```

---

### 3.3 Section Creation

A section represents a distinct physical area of the store (typically one per
floor). Most stores start with one section.

**UI action:** In the store config editor (`/store/{slug}/config/edit`), if no
section exists, the UI prompts to create one. Name it (e.g. "Ground Floor").

**Capture `SECTION_ID`:**

**[WIN]**
```powershell
$sections = Invoke-RestMethod -Uri "http://localhost:8000/api/store/$STORE_SLUG/sections" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$SECTION_ID = $sections[0].id
"SECTION_ID=$SECTION_ID"
```

**[LIN/ORIN]**
```bash
SECTION_ID=$(curl -sf http://localhost:8000/api/store/$STORE_SLUG/sections \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "SECTION_ID=$SECTION_ID"
```

---

### 3.4 Draft Version Creation

All store configuration changes happen within a draft version. The draft must
be explicitly activated to take effect.

**UI action:** Click **Edit Configuration** on the store config page. If no
draft exists, the UI creates one automatically.

**Capture `VERSION_DRAFT_ID`:**

**[WIN]**
```powershell
$draft = Invoke-RestMethod -Uri "http://localhost:8000/api/store/$STORE_SLUG/versions/draft" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$VERSION_DRAFT_ID = $draft.id
"VERSION_DRAFT_ID=$VERSION_DRAFT_ID"
```

**[LIN/ORIN]**
```bash
VERSION_DRAFT_ID=$(curl -sf http://localhost:8000/api/store/$STORE_SLUG/versions/draft \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "VERSION_DRAFT_ID=$VERSION_DRAFT_ID"
```

**DB verification:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c \
  "SELECT id, status, created_at FROM store_config_versions WHERE store_id='$STORE_ID' ORDER BY created_at DESC LIMIT 3;"
# Expected: 1 row with status='draft'
```

---

### 3.5 Floor Plan Upload and Configuration

The floor plan image defines the 2D coordinate space used for all tracking
positions. Quality requirements:

- Image format: PNG or JPEG
- Resolution: ≥ 1000 × 1000 px recommended
- The image must be to scale and oriented consistently with camera views
- Real-world dimensions must be known for scale calibration

**3.5.1 Upload floor plan image**

**UI action:** In the section editor, click **Upload Floor Plan**. Select the
prepared floor plan image file.

**Verify the upload:**

**[WIN]**
```powershell
$fp = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/floor-plan" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
"Floor plan ID: $($fp.id)"
"Image S3 key: $($fp.image_s3_key)"
"Dimensions: $($fp.image_width) x $($fp.image_height)"
# Expected: non-null id, s3_key, and pixel dimensions
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/floor-plan \
    -H "Authorization: Bearer $JWT_TOKEN" | python3 -m json.tool
```

**3.5.2 Set scale reference**

Scale links pixel distances to real-world metres. Two reference points must
be clicked on the floor plan, with the known real-world distance between them.

**UI action:** Click **Set Scale**. Click two known points on the floor plan
(e.g. two ends of a known wall). Enter the real-world distance in metres.

**Verify scale was saved:**

**[WIN]**
```powershell
$fp = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/floor-plan" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
"pixels_per_metre: $($fp.pixels_per_metre)"
# Expected: a positive float (e.g. 32.5) — 0 or null means scale not set
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/floor-plan \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'pixels_per_metre: {d.get(\"pixels_per_metre\")}')"
```

---

### 3.6 Zone Definition

Zones are polygon regions on the floor plan used for occupancy and dwell-time
analytics. At least one zone is required for IEP3 to produce zone-level output.

**Quality requirements:**
- Polygon must be non-degenerate (minimum 3 vertices, non-zero area)
- No two zones should overlap (IEP3 assigns one zone per position)
- Zones should cover all areas of commercial interest

**UI action:** In the zone editor, click **Add Zone**, draw the polygon on the
floor plan, name it (e.g. "Entrance", "Aisle A"), and save.

Repeat for each zone.

**Verify zones:**

**[WIN]**
```powershell
$zones = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/zones" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
"Zone count: $($zones.Count)"
foreach ($z in $zones) { "  Zone: $($z.name)  vertices: $($z.polygon.coordinates[0].Count)" }
# Expected: count >= 1, each zone has >= 3 vertices
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/zones \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "
import sys,json
zones = json.load(sys.stdin)
print(f'Zone count: {len(zones)}')
for z in zones:
    coords = z.get('polygon',{}).get('coordinates',[[]])[0]
    print(f'  {z[\"name\"]}: {len(coords)} vertices')
"
```

---

### 3.7 Physical Camera Registration

Physical cameras represent real hardware devices. Each camera gets a UUID that
persists across config version changes.

**UI action:** In the config editor, click **Add Camera**. Fill in:

| Field | Value |
|---|---|
| Name | Descriptive name (e.g. "Entrance Camera", "Aisle Cam 1") |
| RTSP URL | Full RTSP stream URL (e.g. `rtsp://192.168.1.100/stream`) |
| Model | Camera model (optional) |

Repeat for each camera. Typical store: 2–8 cameras.

> **For dev/test without real cameras:** Use a test video file path instead of
> an RTSP URL. IEP1 accepts file paths via `cv2.VideoCapture`. The file must
> be accessible inside the IEP1 container (e.g. mounted at `/workspace/testing-data/`).

**Capture `CAMERA_ID_1` and `CAMERA_ID_2`:**

**[WIN]**
```powershell
$cameras = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/cameras" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$CAMERA_ID_1 = $cameras[0].id
$CAMERA_ID_2 = if ($cameras.Count -gt 1) { $cameras[1].id } else { $null }
"CAMERA_ID_1=$CAMERA_ID_1"
"CAMERA_ID_2=$CAMERA_ID_2"
```

**[LIN/ORIN]**
```bash
cameras=$(curl -sf http://localhost:8000/api/store/$STORE_SLUG/cameras \
    -H "Authorization: Bearer $JWT_TOKEN")
CAMERA_ID_1=$(echo "$cameras" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
CAMERA_ID_2=$(echo "$cameras" | python3 -c "import sys,json; cs=json.load(sys.stdin); print(cs[1]['id'] if len(cs)>1 else '')")
echo "CAMERA_ID_1=$CAMERA_ID_1"
echo "CAMERA_ID_2=$CAMERA_ID_2"
```

**DB verification:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c \
  "SELECT id, name, rtsp_url, is_active FROM physical_cameras WHERE store_id='$STORE_ID';"
# Expected: one row per registered camera, is_active=true
```

---

### 3.8 Camera Placement on Floor Plan (Camera Configs)

A camera config links a physical camera to a specific position and orientation
on the floor plan within a store version. This is where the camera's field of
view is drawn on the floor plan.

**UI action:** For each camera, click **Place Camera** on the floor plan. Position
the camera icon at the camera's physical location. Optionally draw the field-of-view
cone. Save.

**Capture `CAMERA_CONFIG_ID_1` and `CAMERA_CONFIG_ID_2`:**

**[WIN]**
```powershell
$configs = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/camera-configs" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$CAMERA_CONFIG_ID_1 = ($configs | Where-Object { $_.physical_camera_id -eq $CAMERA_ID_1 }).id
$CAMERA_CONFIG_ID_2 = ($configs | Where-Object { $_.physical_camera_id -eq $CAMERA_ID_2 }).id
"CAMERA_CONFIG_ID_1=$CAMERA_CONFIG_ID_1"
"CAMERA_CONFIG_ID_2=$CAMERA_CONFIG_ID_2"
```

**[LIN/ORIN]**
```bash
configs=$(curl -sf \
    "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/camera-configs" \
    -H "Authorization: Bearer $JWT_TOKEN")
CAMERA_CONFIG_ID_1=$(echo "$configs" | python3 -c "
import sys,json,os
cs=json.load(sys.stdin)
cam=os.environ.get('CAMERA_ID_1','')
match=[c for c in cs if c.get('physical_camera_id')==cam]
print(match[0]['id'] if match else '')
" CAMERA_ID_1="$CAMERA_ID_1")
echo "CAMERA_CONFIG_ID_1=$CAMERA_CONFIG_ID_1"
```

**DB verification:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c \
  "SELECT cc.id, pc.name, cc.version_id, cc.floor_x, cc.floor_y
   FROM camera_configs cc
   JOIN physical_cameras pc ON pc.id = cc.physical_camera_id
   WHERE cc.version_id = '$VERSION_DRAFT_ID';"
# Expected: one row per placed camera with non-null floor_x, floor_y
```

---

### 3.9 Camera Frame Upload

A calibration frame is a single representative image from the camera. It is
used as the canvas for selecting pixel-to-world point correspondences.

**Quality requirements:**
- Frame must be taken from the camera's actual mounted position (not moved)
- Lighting should match operational conditions
- Calibration reference points must be visible in the frame
- Resolution: match the camera's operational stream resolution

**UI action:** For each camera config, click **Upload Frame**. Select the
prepared calibration frame image for that camera.

**Verify frame was uploaded:**

**[WIN]**
```powershell
$config = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$CAMERA_CONFIG_ID_1" `
    -ErrorAction SilentlyContinue `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
"Frame S3 key: $($config.frame_s3_key)"
# Expected: non-null S3 key string
```

**[LIN/ORIN]**
```bash
curl -sf "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/camera-configs" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "
import sys, json, os
cs = json.load(sys.stdin)
cid = os.environ.get('CID','')
match = [c for c in cs if c['id'] == cid]
if match: print('frame_s3_key:', match[0].get('frame_s3_key'))
" CID="$CAMERA_CONFIG_ID_1"
```

---

### 3.10 Homography Calibration

The homography maps pixel coordinates in the camera frame to floor-plan
world coordinates (in metres). It is computed from ≥ 4 point pairs where
the pixel location and the real-world floor position are both known.

**Quality requirements (critical for IEP3 accuracy):**

| Metric | Minimum | Recommended |
|---|---|---|
| Point pairs | 4 | 8–12 |
| Coverage score | ≥ 0.25 | ≥ 0.6 |
| RMS reprojection error | — | < 5 px |
| Max reprojection error | — | < 10 px |
| Point distribution | Not collinear | Spread across frame corners |

**UI action:** For each camera config, click **Calibrate**. For each point:

1. Click a point in the camera frame (pixel coordinates)
2. Click the corresponding point on the floor plan (world coordinates)

Use identifiable physical landmarks: floor tile corners, drain covers, wall
junctions, marked spots. Add ≥ 8 pairs for reliable coverage.

Click **Compute Homography**. Review the reprojection error overlay — each
correspondence should show < 10 px error.

**Capture `CALIBRATION_ID_1`:**

**[WIN]**
```powershell
$cals = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$CAMERA_CONFIG_ID_1/calibrations" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$current = $cals | Where-Object { $_.is_current -eq $true }
$CALIBRATION_ID_1 = $current.id
"CALIBRATION_ID_1=$CALIBRATION_ID_1"
"RMS error: $($current.rms_reprojection_error) px"
"Max error: $($current.max_reprojection_error) px"
"Coverage: $($current.coverage_score)"
"Points: $($current.point_count)"
```

**[LIN/ORIN]**
```bash
cals=$(curl -sf \
    "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$CAMERA_CONFIG_ID_1/calibrations" \
    -H "Authorization: Bearer $JWT_TOKEN")
echo "$cals" | python3 -c "
import sys, json
cals = json.load(sys.stdin)
cur = [c for c in cals if c.get('is_current')]
if cur:
    c = cur[0]
    print(f'CALIBRATION_ID_1={c[\"id\"]}')
    print(f'RMS error:  {c.get(\"rms_reprojection_error\")} px')
    print(f'Max error:  {c.get(\"max_reprojection_error\")} px')
    print(f'Coverage:   {c.get(\"coverage_score\")}')
    print(f'Points:     {c.get(\"point_count\")}')
"
```

**Quality gate** — abort Phase 3 if these fail:

**[WIN]**
```powershell
$rms = [float]$current.rms_reprojection_error
$cov = [float]$current.coverage_score
if ($rms -gt 10.0) { "FAIL: RMS reprojection error $rms px > 10 px threshold — recalibrate" }
elseif ($cov -lt 0.25) { "FAIL: Coverage score $cov < 0.25 — add points in corners" }
else { "PASS: Calibration quality acceptable (RMS=$rms px, coverage=$cov)" }
```

**[LIN/ORIN]**
```bash
echo "$cals" | python3 -c "
import sys, json
cals = json.load(sys.stdin)
cur = next((c for c in cals if c.get('is_current')), None)
if not cur: print('FAIL: no current calibration'); exit(1)
rms = cur.get('rms_reprojection_error') or 999
cov = cur.get('coverage_score') or 0
if rms > 10.0: print(f'FAIL: RMS {rms:.1f} px > 10 px — recalibrate'); exit(1)
elif cov < 0.25: print(f'FAIL: coverage {cov:.2f} < 0.25 — add points in corners'); exit(1)
else: print(f'PASS: RMS={rms:.1f} px, coverage={cov:.2f}')
"
```

**DB verification of calibration matrix:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT id, method, status, is_current,
       rms_reprojection_error, max_reprojection_error, coverage_score, point_count
FROM calibrations
WHERE camera_config_id = '$CAMERA_CONFIG_ID_1'
ORDER BY created_at DESC;
"
# Expected: at least 1 row with status='ok' or 'verified', is_current=true
```

---

### 3.11 Calibration Verification

After reviewing the homography quality metrics in the UI, mark the calibration
as verified. This signals to IEP2 that the projection is trusted.

**UI action:** Click **Verify Calibration** on each camera's calibration result.

**API verification:**

**[WIN]**
```powershell
$cals = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$CAMERA_CONFIG_ID_1/calibrations" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$status = ($cals | Where-Object { $_.is_current }).status
"Calibration status: $status"
if ($status -ne "verified") { "WARN: calibration is '$status', not 'verified'" }
else { "PASS: calibration verified" }
```

**[LIN/ORIN]**
```bash
curl -sf \
    "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$CAMERA_CONFIG_ID_1/calibrations" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    | python3 -c "
import sys,json
cals=json.load(sys.stdin)
cur=next((c for c in cals if c.get('is_current')), None)
status=cur['status'] if cur else 'none'
print(f'status: {status}')
assert status=='verified', f'FAIL: expected verified, got {status}'
print('PASS: calibration verified')
"
```

---

### 3.12 Draft Activation

Activating the draft promotes it to the `active` store_config_version.
IEP2's homography projector, IEP3's camera list, and the Edge Agent all
read from the active version.

**Pre-activation checklist (verify in UI or via API before clicking Activate):**

**[WIN]**
```powershell
# Check all camera configs have a verified calibration
$configs = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/camera-configs" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
foreach ($c in $configs) {
    $cals = Invoke-RestMethod `
        -Uri "http://localhost:8000/api/store/$STORE_SLUG/draft/camera-configs/$($c.id)/calibrations" `
        -Headers @{Authorization="Bearer $JWT_TOKEN"}
    $cur = $cals | Where-Object { $_.is_current }
    $ok = if ($cur.status -eq "verified") { "OK  " } else { "FAIL" }
    "$ok camera_config $($c.id): calibration=$($cur.status)"
}
```

**[LIN/ORIN]**
```bash
configs=$(curl -sf \
    "http://localhost:8000/api/store/$STORE_SLUG/draft/sections/$SECTION_ID/camera-configs" \
    -H "Authorization: Bearer $JWT_TOKEN")
echo "$configs" | python3 -c "
import sys,json,subprocess,os
cs=json.load(sys.stdin)
base='http://localhost:8000/api/store'
slug=os.environ.get('STORE_SLUG','')
tok=os.environ.get('JWT_TOKEN','')
for c in cs:
    import urllib.request as req
    r=req.urlopen(req.Request(f'{base}/{slug}/draft/camera-configs/{c[\"id\"]}/calibrations',headers={'Authorization':f'Bearer {tok}'}))
    cals=json.loads(r.read())
    cur=next((x for x in cals if x.get('is_current')),None)
    st=cur['status'] if cur else 'none'
    tag='OK  ' if st=='verified' else 'FAIL'
    print(f'{tag} config {c[\"id\"][:8]}: calibration={st}')
" STORE_SLUG="$STORE_SLUG" JWT_TOKEN="$JWT_TOKEN"
```

**UI action:** Click **Activate Draft**. Confirm in the dialog.

**Capture `VERSION_ACTIVE_ID` and verify:**

**[WIN]**
```powershell
$active = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/store/$STORE_SLUG/versions/active" `
    -Headers @{Authorization="Bearer $JWT_TOKEN"}
$VERSION_ACTIVE_ID = $active.id
"VERSION_ACTIVE_ID=$VERSION_ACTIVE_ID"
"Status: $($active.status)"
# Expected: status = 'active'
```

**[LIN/ORIN]**
```bash
active=$(curl -sf http://localhost:8000/api/store/$STORE_SLUG/versions/active \
    -H "Authorization: Bearer $JWT_TOKEN")
VERSION_ACTIVE_ID=$(echo "$active" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "VERSION_ACTIVE_ID=$VERSION_ACTIVE_ID"
echo "$active" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status: {d[\"status\"]}')"
# Expected: status: active
```

**DB verification:**

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT v.id, v.status, v.activated_at,
       COUNT(cc.id) AS camera_configs,
       COUNT(z.id)  AS zones
FROM store_config_versions v
LEFT JOIN camera_configs cc ON cc.version_id = v.id
LEFT JOIN sections s ON s.version_id = v.id
LEFT JOIN zones z ON z.section_id = s.id
WHERE v.store_id = '$STORE_ID' AND v.status = 'active'
GROUP BY v.id, v.status, v.activated_at;
"
# Expected: 1 row, status=active, camera_configs >= 1, zones >= 1
```

---

### 3.13 Phase 3 Verification Summary

Run all checks. Every item must pass before proceeding to Phase 4.

**[WIN]**
```powershell
@'
import asyncio, asyncpg, os, sys

STORE_ID = os.environ["STORE_ID"]
ACTIVE_VER = os.environ["ACTIVE_VER"]

async def check():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    failures = []

    # Check store exists and is active
    store = await pool.fetchrow("SELECT id, name FROM stores WHERE id=$1", STORE_ID)
    if not store: failures.append("FAIL: store not found")
    else: print(f"OK:   store '{store['name']}'")

    # Check active version
    ver = await pool.fetchrow("SELECT id, status FROM store_config_versions WHERE id=$1", ACTIVE_VER)
    if not ver or ver['status'] != 'active': failures.append(f"FAIL: active version status={ver['status'] if ver else 'missing'}")
    else: print(f"OK:   active version {ver['id'][:8]}...")

    # Check camera configs have verified calibrations
    cals = await pool.fetch("""
        SELECT cc.id, cal.status, cal.rms_reprojection_error, cal.coverage_score
        FROM camera_configs cc
        LEFT JOIN calibrations cal ON cal.camera_config_id = cc.id AND cal.is_current = true
        WHERE cc.version_id = $1
    """, ACTIVE_VER)
    for c in cals:
        if c['status'] != 'verified':
            failures.append(f"FAIL: camera_config {str(c['id'])[:8]} calibration={c['status']}")
        elif (c['rms_reprojection_error'] or 999) > 10.0:
            failures.append(f"FAIL: camera_config {str(c['id'])[:8]} RMS={c['rms_reprojection_error']:.1f} > 10px")
        else:
            print(f"OK:   camera_config {str(c['id'])[:8]} calibration=verified RMS={c['rms_reprojection_error']:.1f}px")

    # Check at least one zone
    zones = await pool.fetchval("""
        SELECT COUNT(*) FROM zones z
        JOIN sections s ON s.id = z.section_id
        WHERE s.version_id = $1
    """, ACTIVE_VER)
    if zones == 0: failures.append("FAIL: no zones defined")
    else: print(f"OK:   {zones} zone(s) defined")

    # Check floor plan has scale set
    fps = await pool.fetch("""
        SELECT pixels_per_metre FROM floor_plans fp
        JOIN sections s ON s.id = fp.section_id
        WHERE s.version_id = $1
    """, ACTIVE_VER)
    for fp in fps:
        if not fp['pixels_per_metre'] or fp['pixels_per_metre'] <= 0:
            failures.append("FAIL: floor plan scale not set")
        else:
            print(f"OK:   floor plan scale = {fp['pixels_per_metre']:.2f} px/m")

    await pool.close()
    if failures:
        for f in failures: print(f)
        sys.exit(1)
    print("\nPASS: Phase 3 complete — all checks passed")

asyncio.run(check())
'@ | python -; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
STORE_ID="$STORE_ID" ACTIVE_VER="$VERSION_ACTIVE_ID" python3 - <<'EOF'
import asyncio, asyncpg, os, sys

STORE_ID = os.environ["STORE_ID"]
ACTIVE_VER = os.environ["ACTIVE_VER"]

async def check():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    failures = []
    store = await pool.fetchrow("SELECT id, name FROM stores WHERE id=$1", STORE_ID)
    if not store: failures.append("FAIL: store not found")
    else: print(f"OK:   store '{store['name']}'")

    ver = await pool.fetchrow("SELECT id, status FROM store_config_versions WHERE id=$1", ACTIVE_VER)
    if not ver or ver['status'] != 'active': failures.append(f"FAIL: version status={ver['status'] if ver else 'missing'}")
    else: print(f"OK:   active version {str(ver['id'])[:8]}...")

    cals = await pool.fetch("""
        SELECT cc.id, cal.status, cal.rms_reprojection_error, cal.coverage_score
        FROM camera_configs cc
        LEFT JOIN calibrations cal ON cal.camera_config_id=cc.id AND cal.is_current=true
        WHERE cc.version_id=$1
    """, ACTIVE_VER)
    for c in cals:
        if c['status'] != 'verified':
            failures.append(f"FAIL: config {str(c['id'])[:8]} calibration={c['status']}")
        elif (c['rms_reprojection_error'] or 999) > 10.0:
            failures.append(f"FAIL: config {str(c['id'])[:8]} RMS={c['rms_reprojection_error']:.1f} > 10px")
        else:
            print(f"OK:   config {str(c['id'])[:8]} verified RMS={c['rms_reprojection_error']:.1f}px")

    zones = await pool.fetchval("""
        SELECT COUNT(*) FROM zones z JOIN sections s ON s.id=z.section_id WHERE s.version_id=$1
    """, ACTIVE_VER)
    if zones == 0: failures.append("FAIL: no zones")
    else: print(f"OK:   {zones} zone(s)")

    fps = await pool.fetch("""
        SELECT pixels_per_metre FROM floor_plans fp
        JOIN sections s ON s.id=fp.section_id WHERE s.version_id=$1
    """, ACTIVE_VER)
    for fp in fps:
        if not fp['pixels_per_metre'] or fp['pixels_per_metre'] <= 0:
            failures.append("FAIL: floor plan scale not set")
        else: print(f"OK:   floor plan {fp['pixels_per_metre']:.2f} px/m")

    await pool.close()
    if failures:
        for f in failures: print(f)
        sys.exit(1)
    print("\nPASS: Phase 3 complete")

asyncio.run(check())
EOF
```

---

## Phase 4 — Edge Service Validation

Validate each edge component individually before running the full pipeline.
All tests in this phase run inside Docker containers. No real RTSP stream is
needed for 4.1–4.4 (synthetic test data is used). Phase 4.5 onward uses the
active store configuration from Phase 3.

### 4.1 YOLO ZMQ Roundtrip

Send a JPEG frame to YOLO via ZMQ and verify person detections come back in
the correct format.

> **Prerequisite:** YOLO service must be SERVING (Phase 2.3).

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec yolo-service python -c "
import zmq, msgpack, cv2, numpy as np, uuid, time

ctx = zmq.Context()
push = ctx.socket(zmq.PUSH)
push.connect('ipc:///tmp/sockets/yolo_input.sock')

pull = ctx.socket(zmq.PULL)
pull.bind('ipc:///tmp/sockets/yolo_output_test-probe.sock')
pull.setsockopt(zmq.RCVTIMEO, 5000)

# Create a minimal JPEG frame (blank — expect 0 detections)
ok, buf = cv2.imencode('.jpg', np.zeros((480, 640, 3), dtype=np.uint8))
req_id = str(uuid.uuid4())

payload = msgpack.packb({
    'request_id':   req_id,
    'camera_id':    'test-probe',
    'timestamp_ms': int(time.time() * 1000),
    'frame':        buf.tobytes(),
}, use_bin_type=True)
push.send(payload)

raw = pull.recv()
resp = msgpack.unpackb(raw, raw=False)
assert resp.get('request_id') == req_id, 'FAIL: request_id mismatch'
detections = resp.get('detections', [])
print(f'PASS: YOLO roundtrip OK — {len(detections)} detections on blank frame')

pull.close(); push.close(); ctx.term()
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec yolo-service python -c "
import zmq, msgpack, cv2, numpy as np, uuid, time

ctx = zmq.Context()
push = ctx.socket(zmq.PUSH)
push.connect('ipc:///tmp/sockets/yolo_input.sock')
pull = ctx.socket(zmq.PULL)
pull.bind('ipc:///tmp/sockets/yolo_output_test-probe.sock')
pull.setsockopt(zmq.RCVTIMEO, 5000)

ok, buf = cv2.imencode('.jpg', np.zeros((480, 640, 3), dtype=np.uint8))
req_id = str(uuid.uuid4())
payload = msgpack.packb({'request_id':req_id,'camera_id':'test-probe','timestamp_ms':int(time.time()*1000),'frame':buf.tobytes()}, use_bin_type=True)
push.send(payload)

raw = pull.recv()
resp = msgpack.unpackb(raw, raw=False)
assert resp.get('request_id') == req_id, 'FAIL: request_id mismatch'
print(f'PASS: YOLO roundtrip OK — {len(resp.get(\"detections\", []))} detections')
pull.close(); push.close(); ctx.term()
"
```

**[ORIN] — verify TensorRT batch size:**
```bash
$COMPOSE logs yolo-service | grep -i "batch\|TRT\|engine"
# Expected: batch size = 32 (or configured YOLO_MAX_BATCH_SIZE)
```

### 4.2 OSNet ZMQ Roundtrip

Send a person crop to OSNet and verify a 512-dim L2-normalised embedding is returned.

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec osnet-service python -c "
import zmq, msgpack, cv2, numpy as np, uuid, time

ctx = zmq.Context()
push = ctx.socket(zmq.PUSH)
push.connect('ipc:///tmp/sockets/osnet_input.sock')
pull = ctx.socket(zmq.PULL)
pull.bind('ipc:///tmp/sockets/osnet_output_test-probe.sock')
pull.setsockopt(zmq.RCVTIMEO, 5000)

# Blank 128x256 crop (typical person crop dimensions)
ok, buf = cv2.imencode('.jpg', np.random.randint(0, 255, (256, 128, 3), dtype=np.uint8))
req_id = str(uuid.uuid4())

payload = msgpack.packb({
    'request_id':   req_id,
    'camera_id':    'test-probe',
    'track_id':     1,
    'timestamp_ms': int(time.time() * 1000),
    'crop':         buf.tobytes(),
}, use_bin_type=True)
push.send(payload)

raw = pull.recv()
resp = msgpack.unpackb(raw, raw=False)
assert resp.get('request_id') == req_id, 'FAIL: request_id mismatch'

emb_bytes = resp.get('embedding')
assert emb_bytes is not None, 'FAIL: no embedding in response'
emb = np.frombuffer(emb_bytes, dtype=np.float32)
assert emb.shape == (512,), f'FAIL: expected (512,) got {emb.shape}'
norm = np.linalg.norm(emb)
assert abs(norm - 1.0) < 1e-5, f'FAIL: embedding not L2-normalised (norm={norm:.6f})'
print(f'PASS: OSNet roundtrip OK — embedding shape={emb.shape} norm={norm:.6f}')

pull.close(); push.close(); ctx.term()
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec osnet-service python -c "
import zmq, msgpack, cv2, numpy as np, uuid, time
ctx=zmq.Context()
push=ctx.socket(zmq.PUSH); push.connect('ipc:///tmp/sockets/osnet_input.sock')
pull=ctx.socket(zmq.PULL); pull.bind('ipc:///tmp/sockets/osnet_output_test-probe.sock')
pull.setsockopt(zmq.RCVTIMEO, 5000)
ok,buf=cv2.imencode('.jpg',np.random.randint(0,255,(256,128,3),dtype=np.uint8))
req_id=str(uuid.uuid4())
payload=msgpack.packb({'request_id':req_id,'camera_id':'test-probe','track_id':1,'timestamp_ms':int(time.time()*1000),'crop':buf.tobytes()},use_bin_type=True)
push.send(payload)
resp=msgpack.unpackb(pull.recv(),raw=False)
assert resp.get('request_id')==req_id,'request_id mismatch'
emb=np.frombuffer(resp['embedding'],dtype=np.float32)
assert emb.shape==(512,),f'shape={emb.shape}'
norm=np.linalg.norm(emb)
assert abs(norm-1.0)<1e-5,f'norm={norm}'
print(f'PASS: OSNet OK shape={emb.shape} norm={norm:.6f}')
pull.close();push.close();ctx.term()
"
```

### 4.3 IEP1 Camera Capture (Synthetic Video)

Add a test camera to IEP1 using a synthetic test video, wait for frame
capture, and verify manifests are published to Redis.

**Create synthetic test video inside IEP1 container:**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import cv2, numpy as np, os
path = '/tmp/test_cam_p4.mp4'
out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 5, (640, 480))
for i in range(150):
    frame = np.full((480, 640, 3), i, dtype=np.uint8)
    out.write(frame)
out.release()
assert os.path.getsize(path) > 1000, 'FAIL: video file empty'
print(f'PASS: test video created at {path}')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon python -c "
import cv2, numpy as np, os
path='/tmp/test_cam_p4.mp4'
out=cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 5, (640,480))
for i in range(150): out.write(np.full((480,640,3),i,dtype=np.uint8))
out.release()
assert os.path.getsize(path)>1000
print(f'PASS: test video at {path}')
"
```

**AddCamera and verify capture:**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc, time
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',
    request_serializer=pb2.CameraConfig.SerializeToString,
    response_deserializer=pb2.AddCameraResponse.FromString)
r = ac(pb2.CameraConfig(
    camera_id='p4-test-cam', rtsp_url='/tmp/test_cam_p4.mp4',
    target_fps=5.0, window_seconds=5.0,
    store_id='00000000-0000-0000-0000-000000000001',
), timeout=5.0)
assert r.success, f'FAIL: {r.error}'
print('AddCamera OK — waiting 7s for capture...')
time.sleep(7)
gs = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/GetStatus',
    request_serializer=pb2.Empty.SerializeToString,
    response_deserializer=pb2.Iep1StatusResponse.FromString)
s = gs(pb2.Empty())
cam = next((c for c in s.cameras if c.camera_id == 'p4-test-cam'), None)
assert cam, 'FAIL: p4-test-cam not in status'
assert cam.status == 'capturing', f'FAIL: status={cam.status}'
assert cam.last_frame_ts > 0, 'FAIL: no frames captured'
print(f'PASS: IEP1 capturing — last_frame_ts={cam.last_frame_ts}')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon python -c "
import grpc, time
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch=grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac=ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',request_serializer=pb2.CameraConfig.SerializeToString,response_deserializer=pb2.AddCameraResponse.FromString)
r=ac(pb2.CameraConfig(camera_id='p4-test-cam',rtsp_url='/tmp/test_cam_p4.mp4',target_fps=5.0,window_seconds=5.0,store_id='00000000-0000-0000-0000-000000000001'),timeout=5.0)
assert r.success,f'FAIL: {r.error}'
print('AddCamera OK — waiting 7s...')
time.sleep(7)
gs=ch.unary_unary('/retailvision.iep1.v1.Iep1Control/GetStatus',request_serializer=pb2.Empty.SerializeToString,response_deserializer=pb2.Iep1StatusResponse.FromString)
s=gs(pb2.Empty())
cam=next((c for c in s.cameras if c.camera_id=='p4-test-cam'),None)
assert cam and cam.status=='capturing' and cam.last_frame_ts>0,f'FAIL: {cam}'
print(f'PASS: IEP1 capturing last_frame_ts={cam.last_frame_ts}')
"
```

**Verify manifests published to Redis:**

**[WIN]**
```powershell
Start-Sleep 8
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import redis, json
r = redis.Redis.from_url('redis://redis:6379/0')
msgs = r.xrange('stream:iep1:p4-test-cam', count=3)
assert msgs, 'FAIL: no manifests in stream:iep1:p4-test-cam'
m = json.loads(msgs[0][1][b'manifest'])
print(f'PASS: {len(msgs)} manifest(s) published')
print(f'  window_start_ms={m[\"window_start_ms\"]} status={m[\"status\"]} frames={m[\"frame_count\"]}')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
sleep 8
$COMPOSE exec iep1-daemon python -c "
import redis, json
r=redis.Redis.from_url('redis://redis:6379/0')
msgs=r.xrange('stream:iep1:p4-test-cam', count=3)
assert msgs,'FAIL: no manifests'
m=json.loads(msgs[0][1][b'manifest'])
print(f'PASS: {len(msgs)} manifest(s)')
print(f'  window={m[\"window_start_ms\"]} status={m[\"status\"]} frames={m[\"frame_count\"]}')
"
```

### 4.4 IEP2 Manifest Processing

Start IEP2 for the test camera and verify it processes the manifest
published by IEP1, writing to tracking_history and publishing batch_complete.

**[WIN]**
```powershell
$env:CAMERA_ID = "p4-test-cam"
$env:WINDOW_SECONDS = "5"
$env:LOCAL_REDIS_URL = "redis://redis:6379/0"
$env:SERVER_REDIS_URL = "redis://redis:6379/0"
$env:STORE_ID = $STORE_ID
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d iep2_vision
Start-Sleep 30
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep2_vision --tail 10
```

**[LIN]**
```bash
CAMERA_ID=p4-test-cam WINDOW_SECONDS=5 \
LOCAL_REDIS_URL=redis://redis:6379/0 \
SERVER_REDIS_URL=redis://redis:6379/0 \
STORE_ID="$STORE_ID" \
$COMPOSE --profile dev up -d iep2_vision
sleep 30
$COMPOSE logs iep2_vision --tail 10
```

**Verify batch_complete published and XACK fired:**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/0')
bc = r.xlen('stream:iep2:batch_complete')
pel = r.xpending('stream:iep1:p4-test-cam', 'iep2_workers')
pending = pel['pending']
print(f'batch_complete entries: {bc}')
print(f'PEL size (expect 0 after XACK): {pending}')
assert bc > 0, 'FAIL: batch_complete not published'
assert pending == 0, 'FAIL: XACK not called — manifest still pending'
print('PASS: IEP2 processed manifest — batch_complete published, XACK fired')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon python -c "
import redis
r=redis.Redis.from_url('redis://redis:6379/0')
bc=r.xlen('stream:iep2:batch_complete')
pel=r.xpending('stream:iep1:p4-test-cam','iep2_workers')
pending=pel['pending']
print(f'batch_complete: {bc}, PEL: {pending}')
assert bc>0,'FAIL: no batch_complete'
assert pending==0,'FAIL: XACK not fired'
print('PASS')
"
```

**Verify tmpfs cleanup after processing:**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import os, glob
files = glob.glob('/dev/shm/frames/p4-test-cam/*.jpg')
print(f'tmpfs frames remaining: {len(files)}')
assert len(files) == 0, f'FAIL: {len(files)} frames not cleaned'
print('PASS: tmpfs cleaned after processing')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon python -c "
import glob
files=glob.glob('/dev/shm/frames/p4-test-cam/*.jpg')
assert len(files)==0,f'FAIL: {len(files)} frames not cleaned'
print('PASS: tmpfs cleaned')
"
```

### 4.5 IEP3 Reconciliation Trigger

Verify that IEP3 picks up the batch_complete from IEP2 and runs reconciliation.
Since the test camera used a blank frame (no detections), reconciliation will
produce no visitor records — this is expected. What matters is that IEP3
consumed the message without error.

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep3_reconciliation --tail 20 | Select-String "batch|consumed|error|Error|FAIL"
# Expected: batch consumed line, no error lines
```

**[LIN/ORIN]**
```bash
$COMPOSE logs iep3_reconciliation --tail 20 | grep -iE "batch|consumed|error|fail"
```

### 4.6 Edge Agent Lifecycle (Jetson Orin only)

**[ORIN]**
```bash
# Verify Edge Agent startup sequence (see INFRA_TESTS.md 2.9 for log pattern)
# Then test StartCamera via EEP gRPC (requires a valid store camera)
journalctl -u retailvision-edge-agent -n 20 --no-pager | grep -E "SERVING|Restored|Connecting|StartCamera|StopCamera"
```

---

## Phase 5 — End-to-End Pipeline with Real Video

### Prerequisites

- Phase 3 complete: active store version with ≥ 2 calibrated cameras
- Real video files available for each camera
- `STORE_ID`, `CAMERA_ID_1`, `CAMERA_ID_2`, `CAMERA_CONFIG_ID_1`, `CAMERA_CONFIG_ID_2` recorded

### 5.1 Video File Preparation

Place test videos in the `testing-data/` directory (mounted read-only at
`/workspace/testing-data/` inside IEP2 and IEP1 containers).

**[WIN]**
```powershell
# Verify testing-data is mounted and videos are accessible
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon ls /workspace/testing-data/
# Expected: list of video files
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon ls /workspace/testing-data/
```

Video requirements for meaningful E2E results:

| Requirement | Value |
|---|---|
| Duration | ≥ 60 seconds (one full `WINDOW_SECONDS` window) |
| Format | MP4, H.264 — compatible with `cv2.VideoCapture` |
| Content | Real people walking through camera view |
| Multi-camera | Person must cross from cam1 FOV into cam2 FOV (for reconciliation) |
| Synchronisation | Cameras should cover the same time period (overlapping timestamps) |

### 5.2 Full Pipeline Run

Set the real `CAMERA_ID` values (registered in Phase 3) and start the pipeline.

**[WIN]**
```powershell
# Set real camera IDs from Phase 3
# The RTSP URL for the test can use the file path — IEP1 calls cv2.VideoCapture(rtsp_url)
$VIDEO_PATH_CAM1 = "/workspace/testing-data/camera1.mp4"
$VIDEO_PATH_CAM2 = "/workspace/testing-data/camera2.mp4"

# Step 1: Add real cameras to IEP1
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',
    request_serializer=pb2.CameraConfig.SerializeToString,
    response_deserializer=pb2.AddCameraResponse.FromString)

for cam_id, rtsp, store in [
    ('$CAMERA_ID_1', '$VIDEO_PATH_CAM1', '$STORE_ID'),
    ('$CAMERA_ID_2', '$VIDEO_PATH_CAM2', '$STORE_ID'),
]:
    r = ac(pb2.CameraConfig(
        camera_id=cam_id, rtsp_url=rtsp, target_fps=5.0,
        window_seconds=60.0, store_id=store,
    ), timeout=5.0)
    status = 'OK' if r.success else f'FAIL: {r.error}'
    print(f'AddCamera {cam_id[:8]}: {status}')
" 2>&1
```

**[LIN/ORIN]**
```bash
VIDEO_PATH_CAM1="/workspace/testing-data/camera1.mp4"
VIDEO_PATH_CAM2="/workspace/testing-data/camera2.mp4"

$COMPOSE exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch=grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac=ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',request_serializer=pb2.CameraConfig.SerializeToString,response_deserializer=pb2.AddCameraResponse.FromString)
for cam_id, rtsp, store in [
    ('$CAMERA_ID_1','$VIDEO_PATH_CAM1','$STORE_ID'),
    ('$CAMERA_ID_2','$VIDEO_PATH_CAM2','$STORE_ID'),
]:
    r=ac(pb2.CameraConfig(camera_id=cam_id,rtsp_url=rtsp,target_fps=5.0,window_seconds=60.0,store_id=store),timeout=5.0)
    print(f'AddCamera {cam_id[:8]}: {\"OK\" if r.success else r.error}')
"
```

**Step 2: Start IEP2 for both cameras:**

Each camera needs its own IEP2 instance (one IEP2 per camera).

**[WIN]**
```powershell
# Camera 1
$env:CAMERA_ID = $CAMERA_ID_1
$env:CAMERA_CONFIG_ID = $CAMERA_CONFIG_ID_1
$env:STORE_ID = $STORE_ID
$env:WINDOW_SECONDS = "60"
$env:LOCAL_REDIS_URL = "redis://redis:6379/0"
$env:SERVER_REDIS_URL = "redis://redis:6379/0"
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d iep2_vision
```

For Camera 2, you must start a second IEP2 container with a different name.
Dev compose does not natively support two iep2_vision instances.
Use `docker run` directly:

```powershell
docker run -d --name iep2-cam2 `
    --network retail-edge_default `
    -v retail-edge_ipc-sockets:/tmp/sockets `
    -v retail-edge_frame-store:/dev/shm/frames `
    -e CAMERA_ID=$CAMERA_ID_2 `
    -e CAMERA_CONFIG_ID=$CAMERA_CONFIG_ID_2 `
    -e STORE_ID=$STORE_ID `
    -e WINDOW_SECONDS=60 `
    -e LOCAL_REDIS_URL=redis://redis:6379/0 `
    -e SERVER_REDIS_URL=redis://redis:6379/0 `
    -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision `
    retail-edge-iep2_vision:latest
```

**[LIN/ORIN]**
```bash
# Camera 1
CAMERA_ID=$CAMERA_ID_1 CAMERA_CONFIG_ID=$CAMERA_CONFIG_ID_1 \
STORE_ID=$STORE_ID WINDOW_SECONDS=60 \
LOCAL_REDIS_URL=redis://redis:6379/0 SERVER_REDIS_URL=redis://redis:6379/0 \
$COMPOSE --profile dev up -d iep2_vision

# Camera 2
docker run -d --name iep2-cam2 \
    --network retail-edge_default \
    -v retail-edge_ipc-sockets:/tmp/sockets \
    -v retail-edge_frame-store:/dev/shm/frames \
    -e CAMERA_ID=$CAMERA_ID_2 \
    -e CAMERA_CONFIG_ID=$CAMERA_CONFIG_ID_2 \
    -e STORE_ID=$STORE_ID \
    -e WINDOW_SECONDS=60 \
    -e LOCAL_REDIS_URL=redis://redis:6379/0 \
    -e SERVER_REDIS_URL=redis://redis:6379/0 \
    -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
    retail-edge-iep2_vision:latest
```

**Wait for the pipeline to process** (video duration + processing overhead):

**[WIN]**
```powershell
Start-Sleep 120   # adjust based on video length
```

**[LIN/ORIN]**
```bash
sleep 120
```

### 5.3 Pipeline Verification

Verify data flows from IEP1 → IEP2 → tracking_history → IEP3 → global_tracking_history.

**[WIN]**
```powershell
@'
import asyncio, asyncpg, os, sys

STORE_ID   = os.environ["STORE_ID"]
CAM_ID_1   = os.environ["CAM_ID_1"]
CAM_ID_2   = os.environ["CAM_ID_2"]

async def verify():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    failures = []

    # tracking_history rows for both cameras
    for cam in [CAM_ID_1, CAM_ID_2]:
        n = await pool.fetchval(
            "SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1 AND store_id=$2",
            cam, STORE_ID,
        )
        tag = "OK  " if n > 0 else "FAIL"
        print(f"{tag} tracking_history rows for camera {cam[:8]}: {n}")
        if n == 0: failures.append(f"FAIL: no tracking rows for camera {cam}")

    # global_tracking_history rows (IEP3 output)
    gn = await pool.fetchval(
        "SELECT COUNT(*) FROM global_tracking_history WHERE store_id=$1", STORE_ID
    )
    print(f"{'OK  ' if gn > 0 else 'WARN'} global_tracking_history rows: {gn}")
    if gn == 0:
        print("  WARN: IEP3 produced no global rows — this is expected if no people were detected")

    # global_identities (unique persons)
    gi = await pool.fetchval(
        "SELECT COUNT(DISTINCT global_id) FROM global_tracking_history WHERE store_id=$1", STORE_ID
    )
    print(f"  Unique global IDs: {gi}")

    # floor_x / floor_y must be non-null (requires calibration)
    no_pos = await pool.fetchval("""
        SELECT COUNT(*) FROM global_tracking_history
        WHERE store_id=$1 AND (floor_x IS NULL OR floor_y IS NULL)
    """, STORE_ID)
    if no_pos > 0:
        failures.append(f"FAIL: {no_pos} global_tracking rows have null floor positions")
    else:
        print("OK:   all global rows have floor positions")

    await pool.close()
    if failures:
        for f in failures: print(f)
        sys.exit(1)
    print("\nPASS: Pipeline verification complete")

asyncio.run(verify())
'@ | python -; "Exit=$LASTEXITCODE"
```

**[LIN/ORIN]**
```bash
STORE_ID="$STORE_ID" CAM_ID_1="$CAMERA_ID_1" CAM_ID_2="$CAMERA_ID_2" python3 - <<'EOF'
import asyncio, asyncpg, os, sys
STORE_ID=os.environ["STORE_ID"]; CAM_ID_1=os.environ["CAM_ID_1"]; CAM_ID_2=os.environ["CAM_ID_2"]
async def verify():
    pool=await asyncpg.create_pool("postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",min_size=1,max_size=2,statement_cache_size=0)
    failures=[]
    for cam in [CAM_ID_1,CAM_ID_2]:
        n=await pool.fetchval("SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1 AND store_id=$2",cam,STORE_ID)
        print(f"{'OK  ' if n>0 else 'FAIL'} tracking_history camera {cam[:8]}: {n}")
        if n==0: failures.append(f"no tracking rows for {cam}")
    gn=await pool.fetchval("SELECT COUNT(*) FROM global_tracking_history WHERE store_id=$1",STORE_ID)
    print(f"{'OK  ' if gn>0 else 'WARN'} global rows: {gn}")
    gi=await pool.fetchval("SELECT COUNT(DISTINCT global_id) FROM global_tracking_history WHERE store_id=$1",STORE_ID)
    print(f"  unique global IDs: {gi}")
    no_pos=await pool.fetchval("SELECT COUNT(*) FROM global_tracking_history WHERE store_id=$1 AND (floor_x IS NULL OR floor_y IS NULL)",STORE_ID)
    if no_pos>0: failures.append(f"{no_pos} null positions")
    else: print("OK:   all floor positions non-null")
    await pool.close()
    if failures: [print(f"FAIL: {f}") for f in failures]; sys.exit(1)
    print("\nPASS: Pipeline complete")
asyncio.run(verify())
EOF
```

---

## Phase 6 — Accuracy & Regression

These tests compare pipeline outputs against known ground truth. They require
the Phase 5 pipeline to have completed with real video.

### 6.1 Detection Count Accuracy

Compare YOLO detection counts against manual ground truth.

**Manual ground truth preparation:**
Watch each video file and record, for each 60-second window:
- Number of distinct persons visible
- Number of frames with at least one person

**Automated comparison:**

**[WIN]**
```powershell
@'
import asyncio, asyncpg, os
STORE_ID = os.environ["STORE_ID"]
CAM_ID_1 = os.environ["CAM_ID_1"]
WINDOW_START_MS = int(os.environ.get("WINDOW_START_MS", "0"))   # set to first window start

async def check():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    rows = await pool.fetch("""
        SELECT DISTINCT local_id, COUNT(*) AS frame_count,
               MIN(timestamp_ms) AS first_seen, MAX(timestamp_ms) AS last_seen
        FROM tracking_history
        WHERE camera_id=$1 AND store_id=$2
          AND timestamp_ms >= $3 AND timestamp_ms < $3 + 60000
        GROUP BY local_id
        ORDER BY first_seen
    """, CAM_ID_1, STORE_ID, WINDOW_START_MS)
    print(f"Tracked persons in window: {len(rows)}")
    for r in rows:
        duration_s = (r['last_seen'] - r['first_seen']) / 1000
        print(f"  local_id={str(r['local_id'])[:8]} frames={r['frame_count']} duration={duration_s:.1f}s")
    await pool.close()

asyncio.run(check())
'@ | python -
```

**[LIN/ORIN]**
```bash
STORE_ID="$STORE_ID" CAM_ID_1="$CAMERA_ID_1" WINDOW_START_MS=0 python3 - <<'EOF'
import asyncio, asyncpg, os
STORE_ID=os.environ["STORE_ID"]; CAM_ID_1=os.environ["CAM_ID_1"]
WINDOW_START_MS=int(os.environ.get("WINDOW_START_MS","0"))
async def check():
    pool=await asyncpg.create_pool("postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",min_size=1,max_size=2,statement_cache_size=0)
    rows=await pool.fetch("SELECT DISTINCT local_id, COUNT(*) AS fc, MIN(timestamp_ms) AS fs, MAX(timestamp_ms) AS ls FROM tracking_history WHERE camera_id=$1 AND store_id=$2 AND timestamp_ms>=$3 AND timestamp_ms<$3+60000 GROUP BY local_id ORDER BY fs",CAM_ID_1,STORE_ID,WINDOW_START_MS)
    print(f"Tracked persons: {len(rows)}")
    for r in rows:
        print(f"  {str(r['local_id'])[:8]} frames={r['fc']} duration={(r['ls']-r['fs'])/1000:.1f}s")
    await pool.close()
asyncio.run(check())
EOF
```

**Accept criteria:** Person count from DB within ±10% of manual ground truth count.

### 6.2 Cross-Camera Reconciliation Accuracy

Verify that a person who walked from camera 1's view into camera 2's view
received a single `global_id` (not two separate identities).

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT
    gi.global_id,
    COUNT(DISTINCT glm.camera_id) AS camera_count,
    MIN(gth.timestamp_ms) AS entry_ms,
    MAX(gth.timestamp_ms) AS exit_ms,
    ROUND((MAX(gth.timestamp_ms) - MIN(gth.timestamp_ms)) / 1000.0, 1) AS duration_s
FROM global_identities gi
JOIN global_local_mapping glm ON glm.global_id = gi.global_id
JOIN global_tracking_history gth ON gth.global_id = gi.global_id AND gth.store_id = '$STORE_ID'
WHERE gi.store_id = '$STORE_ID'
GROUP BY gi.global_id
HAVING COUNT(DISTINCT glm.camera_id) > 1
ORDER BY duration_s DESC;
"
# Expected: rows with camera_count >= 2 for persons who crossed between cameras
```

**Accept criteria:** At least one `global_id` spans both cameras for a test run
where a person crossed between camera coverage areas.

### 6.3 Floor Position Accuracy

Verify that floor positions fall within the expected zone boundaries.
A person who walked through "Entrance" zone should have `zone_id` matching
the entrance zone UUID for those frames.

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT
    z.name AS zone_name,
    COUNT(*) AS position_count,
    AVG(gth.floor_x) AS avg_x,
    AVG(gth.floor_y) AS avg_y
FROM global_tracking_history gth
JOIN zones z ON z.id = gth.zone_id
WHERE gth.store_id = '$STORE_ID'
GROUP BY z.name
ORDER BY position_count DESC;
"
```

**Accept criteria:**
- `avg_x` and `avg_y` should fall within the polygon defined for that zone
- Zone attribution should match visual review of the video (person in entrance zone → `zone_id` = entrance UUID)

### 6.4 Analytics Query Validation

**[WIN]**
```powershell
@'
import asyncio, asyncpg, os
STORE_ID = os.environ["STORE_ID"]
async def analytics():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    # Total unique visitors (global persons) this store has seen
    visitors = await pool.fetchval(
        "SELECT COUNT(*) FROM global_identities WHERE store_id=$1 AND is_employee=false", STORE_ID
    )
    print(f"Total unique visitors: {visitors}")

    # Zone occupancy breakdown
    rows = await pool.fetch("""
        SELECT z.name, COUNT(DISTINCT gth.global_id) AS unique_visitors,
               COUNT(*) AS total_positions,
               ROUND(AVG(gth.floor_x)::numeric, 2) AS avg_floor_x,
               ROUND(AVG(gth.floor_y)::numeric, 2) AS avg_floor_y
        FROM global_tracking_history gth
        JOIN zones z ON z.id = gth.zone_id
        WHERE gth.store_id=$1
        GROUP BY z.name ORDER BY unique_visitors DESC
    """, STORE_ID)
    print(f"\nZone occupancy:")
    for r in rows:
        print(f"  {r['name']}: {r['unique_visitors']} visitors, {r['total_positions']} positions")

    # Camera coverage (which cameras contributed most data)
    cams = await pool.fetch("""
        SELECT source_camera, COUNT(*) AS rows, COUNT(DISTINCT global_id) AS persons
        FROM global_tracking_history WHERE store_id=$1 GROUP BY source_camera
    """, STORE_ID)
    print(f"\nCamera contributions:")
    for c in cams:
        print(f"  camera={c['source_camera'][:8]}: {c['rows']} rows, {c['persons']} persons")

    await pool.close()
asyncio.run(analytics())
'@ | python -
```

**[LIN/ORIN]**
```bash
STORE_ID="$STORE_ID" python3 - <<'EOF'
import asyncio, asyncpg, os
STORE_ID=os.environ["STORE_ID"]
async def analytics():
    pool=await asyncpg.create_pool("postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",min_size=1,max_size=2,statement_cache_size=0)
    visitors=await pool.fetchval("SELECT COUNT(*) FROM global_identities WHERE store_id=$1 AND is_employee=false",STORE_ID)
    print(f"Unique visitors: {visitors}")
    rows=await pool.fetch("SELECT z.name, COUNT(DISTINCT gth.global_id) AS uv, COUNT(*) AS pos FROM global_tracking_history gth JOIN zones z ON z.id=gth.zone_id WHERE gth.store_id=$1 GROUP BY z.name ORDER BY uv DESC",STORE_ID)
    for r in rows: print(f"  {r['name']}: {r['uv']} visitors {r['pos']} positions")
    await pool.close()
asyncio.run(analytics())
EOF
```

---

## Appendix — Test Data Requirements

### Video footage

| Property | Requirement |
|---|---|
| Duration | ≥ 60 seconds per camera; recommend ≥ 5 minutes for full reconciliation test |
| FPS | Match `target_fps` (default 5 fps) — higher FPS videos are subsampled by IEP1 |
| Resolution | Match camera_config `image_width` × `image_height` |
| Content | Real people walking naturally — not staged crowd, not stationary |
| Coverage | ≥ 1 person crossing from cam1 FOV into cam2 FOV |
| Format | H.264 MP4, readable by `cv2.VideoCapture` |
| Storage location | `retail-edge/testing-data/{camera_name}.mp4` (mounted into containers) |

### Calibration frames

| Property | Requirement |
|---|---|
| Source | Captured from camera at its exact mounted position |
| Timing | Same conditions as operational video (same lens, same zoom) |
| Resolution | Exactly matches operational stream resolution |
| Reference points | ≥ 8 clearly identifiable points visible in frame and measurable on floor |

### Ground truth records

Prepare these manually by watching the video before running Phase 6:

| Record | What to measure |
|---|---|
| Person count per window | Count distinct persons visible in each 60-second clip |
| Cross-camera crossings | Count persons who exit cam1 FOV and enter cam2 FOV |
| Zone dwell times | Time each person spends in each zone (seconds) |
| Entry/exit timestamps | When each person first and last appears on camera |

Store these in `testing-data/ground_truth.json`:

```json
{
  "window_1": {
    "start_ms": 0,
    "end_ms": 60000,
    "camera_1_persons": 3,
    "camera_2_persons": 2,
    "cross_camera_crossings": 1,
    "zone_dwell": {
      "Entrance": 12.5,
      "Aisle A": 34.0
    }
  }
}
```

### `WINDOW_SECONDS` consistency rule

`WINDOW_SECONDS` must be identical across IEP1, IEP2, and IEP3.
A mismatch causes silent reconciliation failure (manifests span different
time intervals than IEP3 expects).

Current default: `60` seconds (set in `docker-compose.yml` `x-shared-config`).

Verify all three use the same value:

**[WIN/LIN/ORIN]**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon env | grep WINDOW
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep2_vision env | grep WINDOW
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep3_reconciliation env | grep WINDOW
# All three must show identical WINDOW_SECONDS value
```
