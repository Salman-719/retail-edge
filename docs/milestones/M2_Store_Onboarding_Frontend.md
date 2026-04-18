# Milestone 2: Store Onboarding Pipeline & Frontend Foundation

**Duration:** 2 weeks
**Dependencies:** M1
**Goal:** Complete store onboarding workflow (floor plan, zones, shelves, cameras, calibration) with React frontend.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| React app scaffolding + routing | DONE | 6 pages, React Router v6 |
| Floor plan upload | DONE | S3 upload via EEP, displayed on canvas |
| Floor plan drawing tool (fallback) | DONE | Konva.js grid-based drawing |
| Zone definition UI (polygons) | DONE | Step3_Zones.jsx, Konva polygons |
| Shelf/obstacle placement | DONE | Obstacles with polygon points |
| Camera registration UI | DONE | Step4_Cameras.jsx, Konva placement |
| Calibration pipeline (homography) | DONE | Step6 correspondence + Step7 compute |
| Verification view | DONE | Step9_TestMode with tracking overlay |
| Employee enrollment API | NOT STARTED | Deferred to M3 |
| Integration tests | NOT STARTED | |
| Zone overlap validation | NOT STARTED | |

**Overall: ~80% complete**

---

## Remaining Tasks

### 1. Employee Enrollment API (Stub)

**Files to create/modify:**

`services/eep/app/api/employees.py`:
```
POST /api/stores/{store_id}/employees
  - Create employee profile (name, role)
  - Save to employees table
  - Return employee record

GET /api/stores/{store_id}/employees
  - List all employees for a store

DELETE /api/employees/{employee_id}
  - Remove employee

POST /api/employees/{employee_id}/enroll
  - Placeholder for ReID enrollment (actual capture in M3)
  - Accept image crops, store temporarily
```

Register router in `services/eep/app/main.py`.

### 2. Zone Overlap Validation

**File:** `services/eep/app/api/zones.py`

On zone create/update:
- Use Shapely `Polygon.intersects()` to check against existing zones in the same store
- Return 409 Conflict if overlap detected
- Frontend should display error message

### 3. Integration Tests for Onboarding Flow

**File:** `tests/integration/test_onboarding_flow.py`

Test the full sequence:
```
1. POST /api/stores              --> create store
2. POST /api/stores/{id}/floor-plans --> upload floor plan
3. POST /api/stores/{id}/zones   --> create zones (verify no overlap rejection)
4. POST /api/stores/{id}/cameras --> register camera
5. POST /api/cameras/{id}/calibration --> compute homography
6. Verify all entities are retrievable via GET
7. DELETE store --> verify cascade
```

Use `httpx.AsyncClient` with the FastAPI test client.

### 4. Frontend Tests

**File:** `frontend/src/__tests__/`

Priority tests:
- `api.test.js` — mock fetch, verify saveProject, loadProject
- `store.test.js` — Zustand store actions
- `Step3_Zones.test.jsx` — zone polygon creation/deletion

Use Vitest (already in Vite ecosystem).

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `frontend/src/pages/StoreOnboarding.jsx` | 9-step wizard orchestrator |
| `frontend/src/steps/Step1_Upload.jsx` | Floor plan upload |
| `frontend/src/steps/Step2_Scale.jsx` | Scale calibration (Konva) |
| `frontend/src/steps/Step3_Zones.jsx` | Zone polygon drawing (Konva) |
| `frontend/src/steps/Step4_Cameras.jsx` | Camera placement (Konva) |
| `frontend/src/steps/Step5_Videos.jsx` | Video upload |
| `frontend/src/steps/Step6_Correspondence.jsx` | Point correspondence (Konva) |
| `frontend/src/steps/Step7_Homography.jsx` | Homography computation |
| `frontend/src/steps/Step8_Save.jsx` | Config editor + save to DB |
| `frontend/src/steps/Step9_TestMode.jsx` | Tracking verification (Konva) |
| `services/eep/app/api/stores.py` | Store CRUD |
| `services/eep/app/api/zones.py` | Zone CRUD |
| `services/eep/app/api/cameras.py` | Camera CRUD |
| `services/eep/app/api/calibration.py` | Homography endpoints |

---

## Evaluation Criteria (must pass before M3)

- [ ] Floor plan uploads and displays correctly
- [ ] Zones can be drawn, named, saved, and retrieved
- [ ] Overlapping zones are rejected with clear error
- [ ] Obstacles can be placed and edited on floor plan
- [ ] Camera registered with position and RTSP URL
- [ ] Calibration computes valid homography (reprojection error < 0.5m on test points)
- [ ] Employee CRUD endpoints work
- [ ] Integration tests pass
- [ ] Frontend unit tests pass

## Re-iteration Triggers

- If calibration accuracy poor (>1m error): increase reference points, verify non-collinearity
- If Konva.js insufficient: evaluate Fabric.js (we chose Konva, working well)
- If zone overlap logic false-positives: adjust Shapely tolerance, test with edge cases
