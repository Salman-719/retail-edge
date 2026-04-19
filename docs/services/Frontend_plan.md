# Frontend — React Dashboard

**Role:** Single-page React app that talks **only** to EEP. Delivers the four UX surfaces: store onboarding wizard, live monitoring, analytics dashboard, AI-agent chat.

**Source:** `frontend/`
**Stack:** React 18, Vite, Zustand (state), React Router v6, Konva.js (canvas), Recharts (charts), react-markdown, TailwindCSS.

---

## Surfaces

| Surface | Route | Owner page | Status |
|---------|-------|------------|--------|
| Onboarding wizard (9 steps) | `/onboarding/:storeId?` | `pages/StoreOnboarding.jsx` | DONE |
| Store config editor | `/config/:storeId` | `pages/StoreConfig.jsx` | DONE |
| Live monitoring | `/live/:storeId` | `pages/LiveMonitoring.jsx` | STUB |
| Analytics | `/analytics/:storeId` | `pages/Analytics.jsx` | STUB |
| AI agent | `/agent/:storeId` | `pages/AIAgent.jsx` | STUB |
| Login | `/login` | `pages/Login.jsx` | STUB |

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Vite + React 18 + Router + Tailwind | DONE | |
| Sidebar navigation (6 routes) | DONE | |
| Onboarding wizard | DONE | Konva.js, 9 steps |
| Floor plan upload + fallback drawing | DONE | |
| Zone polygon tool | DONE | |
| Obstacle placement | DONE | |
| Camera placement | DONE | |
| Homography (correspondence → compute) | DONE | |
| Test-mode tracking overlay | DONE | |
| Config save/load | DONE | |
| Live monitoring view | NOT STARTED | M9 |
| Analytics dashboard | NOT STARTED | M9 |
| AI agent chat | NOT STARTED | M9 |
| POS upload UI | NOT STARTED | M9 |
| Report viewer | NOT STARTED | M9 |
| Vitest + React Testing Library | NOT STARTED | M2/M9 |
| ESLint in CI | NOT STARTED | M1 |

**Overall: ~35%** (onboarding complete, three pages are stubs).

---

## Onboarding Wizard (DONE — reference)

| Step | File | Purpose |
|------|------|---------|
| 1 | `steps/Step1_Upload.jsx` | Floor plan upload |
| 2 | `steps/Step2_Scale.jsx` | Scale calibration (Konva) |
| 3 | `steps/Step3_Zones.jsx` | Zone polygons (Konva) |
| 4 | `steps/Step4_Cameras.jsx` | Camera placement |
| 5 | `steps/Step5_Videos.jsx` | Video upload |
| 6 | `steps/Step6_Correspondence.jsx` | Point correspondence |
| 7 | `steps/Step7_Homography.jsx` | Compute homography |
| 8 | `steps/Step8_Save.jsx` | Config editor + save |
| 9 | `steps/Step9_TestMode.jsx` | Tracking verification |

---

## M9 — Live Monitoring

**File:** `pages/LiveMonitoring.jsx` (rewrite)

Layout:
```
┌ Store picker ─────────── Last updated ┐
├─────────────┬────────────────────────┤
│ Floor plan  │ Camera grid (2×4)      │
│ (Konva +    │ MJPEG per camera       │
│  live dots) │ count overlay          │
├─────────────┴────────────────────────┤
│ Metrics bar [Headcount][Queue][Staff][Alerts] │
├───────────────────────────────────────┤
│ Active alerts table                   │
└───────────────────────────────────────┘
```

Data (polled 30 s unless noted):
- `GET /api/stores/{sid}/tracking/progress` — per camera
- `GET /api/alerts/{sid}`
- `GET /api/stores/{sid}/tracking/trajectory` — latest positions (project via homography in JS)
- MJPEG: `<img src="/api/tracking/{sid}/cameras/{cid}/stream" />`

Components to create under `components/monitoring/`:
- `FloorPlanLive.jsx` — Konva canvas, live dots, zone highlights
- `CameraGrid.jsx` — grid of MJPEG streams
- `MetricsBar.jsx` — metric cards
- `AlertPanel.jsx` — active alerts table with acknowledge

---

## M9 — Analytics Dashboard

**File:** `pages/Analytics.jsx` (rewrite)

Layout:
```
Store picker | Date range picker | Tab bar [Today|Week|Month|Custom]
┌─────────────────┬───────────────────┐
│ Heatmap overlay │ Zone traffic (bar)│
├─────────────────┼───────────────────┤
│ Headcount (line)│ Flow (Sankey)     │
├─────────────────┴───────────────────┤
│ Classification (pie) | POS (scatter)│
├─────────────────────────────────────┤
│ Alert history table                  │
└─────────────────────────────────────┘
```

Data:
- `GET /api/analytics/{sid}/summary`
- `GET /api/analytics/{sid}/zones`
- `GET /api/analytics/{sid}/traffic?granularity=hour`
- `GET /api/analytics/{sid}/flow`
- `GET /api/analytics/{sid}/heatmap` (image URL)
- `GET /api/analytics/{sid}/pos/correlation`
- `GET /api/alerts/{sid}`

Dependencies: `recharts`, `react-markdown`, `remark-gfm`, date range lib (`react-day-picker`).

Components under `components/analytics/`:
- `HeatmapOverlay.jsx`
- `ZoneTrafficChart.jsx`
- `HeadcountTrend.jsx`
- `FlowDiagram.jsx` (Sankey)
- `ClassificationPie.jsx`
- `POSCorrelation.jsx`
- `POSUpload.jsx` — CSV picker, progress bar, row-level validation preview
- `AlertHistory.jsx` — paginated table
- `DateRangePicker.jsx`

---

## M9 — AI Agent

**File:** `pages/AIAgent.jsx` (rewrite)

Layout: chat messages + suggested-question chips + input + Reports tab.

Data:
- `POST /api/agent/query` → streaming or single response (text + inline charts)
- `POST /api/agent/report` → markdown + charts
- `GET /api/agent/suggestions/{sid}`

Components under `components/agent/`:
- `ChatMessage.jsx` — user / assistant bubbles with markdown rendering
- `InlineChart.jsx` — renders chart spec returned by agent (base64 PNG or Recharts)
- `SuggestedQuestions.jsx` — clickable chips
- `ReportViewer.jsx` — markdown report, html2canvas + jsPDF export
- `TypingIndicator.jsx`

---

## Testing (Vitest + RTL)

**Directory:** `frontend/src/__tests__/`

Priority:
- `api.test.js` — mock `fetch`, verify `saveProject`, `loadProject`
- `store.test.js` — Zustand actions
- `Step3_Zones.test.jsx` — polygon create/delete
- `LiveMonitoring.test.jsx` — renders with mock data
- `Analytics.test.jsx` — charts render with mock data
- `AIAgent.test.jsx` — chat flow happy path

CI: add `eslint frontend/src` and `vitest run` to `.github/workflows/ci.yml`.

---

## API Client Conventions

- Single base URL: `VITE_EEP_URL` (defaults to `http://localhost:8000`).
- All calls go through `frontend/src/api/client.js` — central `fetch` wrapper with JSON handling, error normalisation, API-key header injection (M8).
- Zustand store in `frontend/src/store/` holds store-config state; never duplicate server state — refetch.

---

## Evaluation Criteria

- [x] Onboarding wizard completes end-to-end
- [x] Zones / obstacles / cameras round-trip through save/load
- [ ] Live monitoring refreshes every 30 s with current data
- [ ] Camera MJPEG streams render in grid
- [ ] Floor plan shows live person dots (homography in JS)
- [ ] Analytics renders heatmaps + all chart types with real data
- [ ] Date range picker re-queries analytics
- [ ] Chat flow displays multi-turn responses with inline charts
- [ ] POS CSV uploads with row-level errors surfaced
- [ ] Vitest suite ≥ 20 tests, all pass
- [ ] ESLint in CI, zero errors on PR

---

## Re-iteration Triggers

- Dashboard slow → `React.memo`, virtualise long lists, paginate API calls
- Charts mis-render → verify Recharts data shape matches IEP4 response
- MJPEG lags → reduce JPEG quality, increase frame buffer
- Chat flicker on token stream → use `startTransition` for incremental appends
