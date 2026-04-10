# Milestone 9: Frontend Dashboard Completion

**Duration:** 1.5 weeks
**Dependencies:** M5, M6
**Goal:** Complete React dashboard with all four sections: onboarding (from M2), live monitoring, analytics, and AI agent interface.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Onboarding wizard (9 steps) | DONE | Konva.js, fully functional |
| Store Config page | DONE | Inline editing, per-store |
| Sidebar navigation | DONE | 6 routes |
| LiveMonitoring page | STUB | Empty placeholder |
| Analytics page | STUB | Empty placeholder |
| AIAgent page | STUB | Empty placeholder |
| Login page | STUB | Empty placeholder |
| POS upload UI | NOT STARTED | |
| Report viewer | NOT STARTED | |
| Jest/Vitest tests | NOT STARTED | |

**Overall: ~35% complete** (onboarding done, 3 major pages are stubs)

---

## Implementation Tasks

### 1. Live Monitoring View

**File:** `frontend/src/pages/LiveMonitoring.jsx` — full rewrite

```
Layout:
┌─────────────────────────────────────────────────┐
│  Store Selector (dropdown)         Last Updated  │
├──────────────┬──────────────────────────────────┤
│              │                                    │
│  Floor Plan  │  Camera Grid (2x4)                │
│  (Konva)     │  - MJPEG stream per camera        │
│  with live   │  - Detection count overlay        │
│  person dots │  - Status indicator               │
│              │                                    │
├──────────────┴──────────────────────────────────┤
│  Metrics Bar                                      │
│  [Headcount: 34] [Queue: 5] [Staff: 8] [Alerts:2]│
├──────────────────────────────────────────────────┤
│  Active Alerts Panel                              │
│  - Type | Zone | Severity | Time | Action        │
└──────────────────────────────────────────────────┘
```

**Data sources:**
```javascript
// Poll every 30 seconds:
GET /api/stores/{store_id}/tracking/progress  // per camera
GET /api/stores/{store_id}/alerts             // via IEP3

// MJPEG streams (direct):
<img src="/api/tracking/{store_id}/cameras/{cam_id}/stream" />

// Floor plan person positions:
GET /api/stores/{store_id}/tracking/trajectory  // latest positions
// Project onto floor plan canvas using homography (client-side)
```

**Components to create:**
- `components/monitoring/FloorPlanLive.jsx` — Konva canvas with person dots, zone highlights
- `components/monitoring/CameraGrid.jsx` — grid of MJPEG streams
- `components/monitoring/MetricsBar.jsx` — key metric cards
- `components/monitoring/AlertPanel.jsx` — active alerts table with acknowledge button

### 2. Analytics Dashboard

**File:** `frontend/src/pages/Analytics.jsx` — full rewrite

```
Layout:
┌─────────────────────────────────────────────────┐
│  Store Selector    Date Range Picker    Tab Bar  │
│                    [Today|Week|Month|Custom]      │
├─────────────────────┬───────────────────────────┤
│                     │                             │
│  Heatmap Overlay    │  Zone Traffic Chart         │
│  (floor plan +      │  (Recharts BarChart)        │
│   color overlay)    │                             │
│                     │                             │
├─────────────────────┼───────────────────────────┤
│                     │                             │
│  Headcount Trend    │  Zone Flow (Sankey or       │
│  (Recharts Line)    │  chord diagram)             │
│                     │                             │
├─────────────────────┴───────────────────────────┤
│  People Classification | POS Correlation          │
│  (Pie chart)           | (Scatter + line)         │
├──────────────────────────────────────────────────┤
│  Alert History Table (paginated, filterable)      │
└──────────────────────────────────────────────────┘
```

**Data sources:**
```javascript
GET /api/analytics/{store_id}/summary?start=...&end=...
GET /api/analytics/{store_id}/zones?start=...&end=...
GET /api/analytics/{store_id}/traffic?start=...&end=...&granularity=hour
GET /api/analytics/{store_id}/flow?start=...&end=...
GET /api/analytics/{store_id}/heatmap?start=...&end=...  // image
GET /api/analytics/{store_id}/pos/correlation?start=...&end=...
GET /api/alerts/{store_id}
```

**Dependencies to add:** `recharts` (or `chart.js` + `react-chartjs-2`)

**Components to create:**
- `components/analytics/HeatmapOverlay.jsx` — floor plan + fetched heatmap PNG overlay
- `components/analytics/ZoneTrafficChart.jsx` — stacked bar chart per zone
- `components/analytics/HeadcountTrend.jsx` — line chart over time
- `components/analytics/FlowDiagram.jsx` — Sankey or alluvial diagram
- `components/analytics/ClassificationPie.jsx` — demographic breakdown
- `components/analytics/POSCorrelation.jsx` — scatter plot with trend line
- `components/analytics/AlertHistory.jsx` — paginated table
- `components/analytics/DateRangePicker.jsx` — reusable date range selector

### 3. AI Agent Chat Interface

**File:** `frontend/src/pages/AIAgent.jsx` — full rewrite

```
Layout:
┌─────────────────────────────────────────────────┐
│  RetailVision AI Agent     Store: [dropdown]     │
├──────────────────────────────────────────────────┤
│                                                    │
│  Chat Messages Area (scrollable)                   │
│                                                    │
│  [User]: How busy was electronics yesterday?       │
│                                                    │
│  [Agent]: Based on yesterday's data...             │
│           ┌────────────────────┐                   │
│           │ [Inline Bar Chart] │                   │
│           └────────────────────┘                   │
│           Electronics had 234 visitors...          │
│                                                    │
│  [User]: Compare with last week                    │
│                                                    │
│  [Agent]: Here's the comparison...                 │
│           ┌────────────────────┐                   │
│           │ [Inline Line Chart]│                   │
│           └────────────────────┘                   │
│                                                    │
├──────────────────────────────────────────────────┤
│  Suggested questions:                              │
│  [Busiest zone?] [Staff coverage?] [Conversion?]  │
├──────────────────────────────────────────────────┤
│  [Message input...                    ] [Send]     │
├──────────────────────────────────────────────────┤
│  Reports Tab: [Daily] [Weekly] [Custom]            │
│  ┌──────────────────────────────────────────────┐ │
│  │ Report content (markdown rendered)            │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**Data sources:**
```javascript
POST /api/agent/query
  Body: { store_id, question, context }
  Response: { answer, confidence, charts[], sources[] }

POST /api/agent/report
  Body: { store_id, report_type, start, end }
  Response: { markdown, charts }

GET /api/agent/suggestions/{store_id}
  Response: [{ title, detail, priority }]
```

**Components to create:**
- `components/agent/ChatMessage.jsx` — render user/agent messages with markdown
- `components/agent/InlineChart.jsx` — render chart specs returned by agent
- `components/agent/SuggestedQuestions.jsx` — clickable suggestion chips
- `components/agent/ReportViewer.jsx` — markdown report with embedded charts
- `components/agent/TypingIndicator.jsx` — animated dots while LLM processes

**Dependencies:** `react-markdown`, `remark-gfm` (for markdown rendering)

### 4. POS Upload UI

**File:** `frontend/src/components/analytics/POSUpload.jsx` (NEW)

```
- File picker (CSV only)
- Upload progress bar
- Validation error display (row-level errors)
- Preview first 10 rows before confirm
- Option to process partial file (skip bad rows)
```

**Endpoint:** `POST /api/analytics/{store_id}/pos/upload` (multipart/form-data)

### 5. Report Viewer

Integrated into AIAgent page (Reports tab):
- List of generated reports (daily/weekly)
- Click to view full markdown + charts
- Download as PDF option (html2canvas + jsPDF)

### 6. Frontend Tests

**Setup:** Add `vitest` + `@testing-library/react` to `package.json`

**Files:**
```
frontend/src/__tests__/
  api.test.js                    -- mock fetch, test API functions
  store.test.js                  -- Zustand store actions
  LiveMonitoring.test.jsx        -- renders with mock data
  Analytics.test.jsx             -- renders charts with mock data
  AIAgent.test.jsx               -- chat flow test
  components/
    AlertPanel.test.jsx
    ZoneTrafficChart.test.jsx
```

### 7. EEP Proxy Routes for IEP3-5

**File:** `services/eep/app/api/proxy.py` (NEW or extend existing)

Add proxy routes so frontend hits EEP only:
```python
# Alerts (IEP3)
GET  /api/alerts/{store_id}           -> IEP3 /alerts/{store_id}
POST /api/alerts/rules                -> IEP3 /alerts/rules
PATCH /api/alerts/{alert_id}          -> IEP3 /alerts/{alert_id}

# Analytics (IEP4)
GET  /api/analytics/{store_id}/summary  -> IEP4
GET  /api/analytics/{store_id}/zones    -> IEP4
GET  /api/analytics/{store_id}/traffic  -> IEP4
POST /api/analytics/{store_id}/pos/upload -> IEP4

# Agent (IEP5)
POST /api/agent/query                 -> IEP5
POST /api/agent/report                -> IEP5
GET  /api/agent/suggestions/{sid}     -> IEP5
```

---

## Evaluation Criteria (must pass before M10)

- [ ] Live monitoring updates correctly every 30s with current data
- [ ] MJPEG camera streams render in grid
- [ ] Floor plan shows live person positions
- [ ] Analytics renders heatmaps, all chart types with real data
- [ ] Date range picker filters analytics correctly
- [ ] AI agent chat sends queries, displays multi-turn responses
- [ ] Inline charts render inside chat messages
- [ ] POS upload works with validation
- [ ] All four dashboard sections functional and navigable
- [ ] Frontend tests pass

## Re-iteration Triggers

- If dashboard slow: add React.memo, virtualize long lists, paginate API calls
- If charts don't render: verify data format from IEP4 matches Recharts expectations
- If MJPEG streams lag: reduce JPEG quality, increase frame buffer
