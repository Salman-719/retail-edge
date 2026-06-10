# Frontend

**Location:** `frontend/`
**Runs on:** Cloud
**Exposes:** :3000 (production Docker build) / :5173 (Vite dev server)
**Depends on:** EEP REST :8000, Live Bridge WebSocket :8010

## 1. Role

React 18 SPA — the sole user-facing interface for the entire platform. Covers
store onboarding, floor-plan configuration, live monitoring, analytics, alerts,
AI agent, employees, shifts, members, audit, and settings.

## 2. Tech stack

| Layer | Library |
|---|---|
| UI framework | React 18 |
| Build tool | Vite |
| Routing | React Router v6 |
| Styling | Tailwind CSS |
| Canvas (floor plan editor) | Konva.js |
| HTTP client | Axios (JWT auto-refresh interceptor) |
| State | Zustand + React context (`store.js`) |

## 3. Build modes

Two ways to run; they are not equivalent:

| Mode | URL | Purpose |
|---|---|---|
| Docker `frontend` service | http://localhost:3000 | Production build (`vite build`) — for verifying the shippable bundle |
| Vite dev server (`npm run dev`) | http://localhost:5173 | Dev build — hot reload, and the `/dev/e2e` pipeline tester |

The `/dev/e2e` route ships in the production bundle but is gated to super-admin
users only (lazy-loaded with `<PrivateRoute adminOnly>`).

## 4. Route map

```
/login                           Public — JWT login
/register                        Public — account creation
/accept-invite                   Public — invite token acceptance
/forgot-password                 Public
/reset-password                  Public

/dashboard                       PrivateRoute — owner store list

/store/:slug/
  live                           Live monitoring — reconciled identities + camera health
  analytics                      IEP5 analytics rollups (visits, dwell, heatmaps, flows)
  alerts                         IEP4 alerts — active/history + rule CRUD
  agent                          IEP6 AI agent — NL Q&A + insight reports
  config                         StoreSetup — floor plan, zones, cameras, schedules (read/split view)
  config/edit                    StoreConfigEdit — versioned draft edit + publish
  config/punch                   StorePunchEditor — employee punch-in station config
  employees                      Employee records + linking
  shifts                         Shift patterns + assignments
  members                        Org members + roles + invite
  audit                          Audit log
  settings                       Store/org settings (admin only)
  dev/e2e                        Pipeline tester — IEP1→IEP2→IEP3 split-screen (super-admin)
```

## 5. Key components

**Floor plan editor** — `StoreSetup.jsx` / `StoreConfigEdit.jsx` using Konva
canvas: places zones and cameras on the floor plan image, overlays homography
calibration points, and drives the versioned draft → publish flow.

**Live Monitoring** — polls `GET /api/live/...` on EEP for reconciled identity
counts and camera/edge-agent health. Opens a WebSocket to Live Bridge
(`ws://localhost:8010/ws/live/{camera_id}`) per active camera to render live
frames + detection overlays.

**Analytics** — reads IEP5 rollups via `GET /store/{slug}/analytics/*`. Charts use
lightweight custom components. Widgets include store series, zone breakdown, flow
matrix, heatmap, distribution, composition, employees, and alerts timeseries.

**Alerts** — reads and resolves IEP4 alerts; manages alert rules via REST CRUD.

**AI Agent** — sends `POST /api/agent/query` to IEP6 and renders the response.

**Dev E2E** (`/dev/e2e`) — full-pipeline tester: camera controls, CPU/GPU toggle,
live feed tiles with per-camera tracking tables, IEP3 reconciled output, and a
unified floor-map overlay. Super-admin gated, lazy-loaded.

## 6. API communication

All REST calls go through `src/api.js` — an Axios instance that:
- Points to `VITE_API_URL` (default `http://localhost:8000`).
- Attaches `Authorization: Bearer <token>` from Zustand auth state.
- Intercepts 401 responses: silently refreshes the JWT and retries once.

WebSocket connections are created directly in the component that needs live data
(currently `LiveMonitoring.jsx`), targeting `VITE_LIVE_BRIDGE_URL`.

## 7. Development

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173  (hot reload + /dev/e2e)
npm run build      # production bundle
npm run preview    # serve production bundle locally
```

Type-check / lint:
```bash
npm run lint
```

The production Docker build passes `VITE_API_URL` and `VITE_LIVE_BRIDGE_URL` as
build-args from `docker-compose.yml` → `Dockerfile` ARG → `ENV`. Changing these
requires a rebuild, not just a restart.
