# Milestone 5: Batch Analytics Pipeline

**Duration:** 1.5 weeks
**Dependencies:** M4
**Goal:** All batch analytics (heatmaps, zone traffic, flow analysis, trends, people classification, POS correlation) generating correct outputs.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Basic heatmap generation | PARTIAL | Zone overlay exists in IEP2, not aggregated in IEP4 |
| Zone traffic aggregation | NOT STARTED | |
| Zone-to-zone flow analysis | NOT STARTED | |
| Headcount trendlines | NOT STARTED | |
| People classification | NOT STARTED | |
| POS data upload + parsing | NOT STARTED | |
| Sales-traffic correlation | NOT STARTED | |
| IEP4 batch scheduler | NOT STARTED | |
| IEP4 schemas/stubs | DONE | schemas.py + main.py with typed endpoints |

**Overall: ~10% complete**

---

## Implementation Tasks

### 1. Analytics Data Persistence

**File:** `services/iep4-analytics/app/core/database.py` (NEW)

Set up async SQLAlchemy session (same pattern as EEP). IEP4 will read from:
- `tracking_results` — trajectory_data, zone_occupancy per tracking job
- `tracking_history` — per-person zone enter/exit events (populated by M4)
- `analytics_results` — aggregated outputs (IEP4 writes here)

### 2. Ingestion Handler (Real Implementation)

**File:** `services/iep4-analytics/app/api/ingest.py` (NEW)

Replace stub in main.py:
```python
POST /analytics/ingest
  Input: TrackingSnapshot (from IEP2 via EEP orchestrator)
  Process:
    1. Parse trajectory data
    2. Compute per-zone entry/exit counts
    3. Compute zone-to-zone transitions
    4. Compute headcount at each timestamp
    5. Store raw snapshot in analytics_results table
    6. Update running aggregates (hourly/daily buckets)
```

### 3. Heatmap Aggregation

**File:** `services/iep4-analytics/app/utils/heatmap.py` (NEW)

```python
def generate_aggregated_heatmap(store_id, start, end):
    """Aggregate trajectory data across time range into a single heatmap.

    Process:
    1. Query all tracking_results for store in [start, end]
    2. Merge trajectory points onto floor plan grid (0.5m cells)
    3. Compute person-seconds per cell
    4. Render as color overlay (matplotlib or OpenCV)
    5. Upload to S3: stores/{store_id}/analytics/heatmap_{period}.png
    6. Return S3 key
    """
```

### 4. Zone Traffic Aggregation

**File:** `services/iep4-analytics/app/utils/zone_traffic.py` (NEW)

```python
def aggregate_zone_traffic(store_id, start, end, granularity="hour"):
    """Count zone entries/exits grouped by time bucket.

    Returns per zone:
    - entry_count, exit_count per bucket
    - avg_dwell_time
    - peak_occupancy
    - total_visitors

    Store in analytics_results with type='zone_traffic'.
    """
```

### 5. Zone-to-Zone Flow Analysis

**File:** `services/iep4-analytics/app/utils/flow.py` (NEW)

```python
def compute_flow_matrix(store_id, start, end):
    """Extract zone transition sequences per person.

    Process:
    1. For each person trajectory, determine zone sequence
    2. Build transition matrix: flow[zone_A][zone_B] = count
    3. Optionally generate Sankey diagram data

    Returns: {
        "matrix": {"Zone A": {"Zone B": 45, "Zone C": 12}},
        "top_paths": [["Entrance", "Aisle 1", "Checkout"], ...],
        "sankey_data": {...}  # for frontend rendering
    }
    """
```

### 6. Headcount Trendlines

**File:** `services/iep4-analytics/app/utils/headcount.py` (NEW)

```python
def compute_headcount_trend(store_id, start, end, granularity="hour"):
    """Query person count snapshots grouped by time bucket.

    Source: Redis person DB snapshots (persisted to tracking_history by M4)
    Returns: list of {timestamp, count} for charting
    """
```

### 7. People Classification (Stretch)

**File:** `services/iep4-analytics/app/utils/classification.py` (NEW)

```python
Group-level clustering:
  - Proximity rule: persons within 1m for >30s = group
  - Co-travel: persons with similar trajectories = group

Person-level attributes (if model available):
  - Age range estimation
  - Gender estimation
  Note: Use pretrained models, do NOT train custom ones

Aggregate distributions by zone and time.
```

### 8. POS Data Upload & Correlation

**Files:**

`services/iep4-analytics/app/api/pos.py` (NEW):
```python
POST /analytics/{store_id}/pos/upload
  Input: CSV file (multipart/form-data)
  Process:
    1. Validate CSV schema (transaction_id, amount, items, timestamp, zone)
    2. Parse with pandas
    3. Store in pos_transactions table
  Output: {rows_imported, errors}

GET /analytics/{store_id}/pos/correlation
  Input: start, end (query params)
  Process:
    1. Join POS data with traffic data by time window
    2. Compute: conversion_rate, revenue_per_visitor, temporal_correlation
  Output: CorrelationResult
```

### 9. Batch Job Scheduler

**File:** `services/iep4-analytics/app/scheduler.py` (NEW)

```python
Use APScheduler or simple background thread:

Jobs:
  - Hourly: aggregate zone traffic for last hour
  - Daily (2 AM): generate daily heatmap, compute flow matrix, headcount trends
  - Weekly (Sunday 3 AM): generate weekly report, POS correlation

Each job:
  1. Query raw data for period
  2. Compute aggregation
  3. Store result in analytics_results table
  4. Update S3 artifacts (heatmaps, charts)
```

### 10. Wire Up IEP4 Endpoints (Replace Stubs)

**File:** `services/iep4-analytics/app/main.py`

Replace placeholder returns with real queries:
```
GET /analytics/{store_id}/summary   -> query analytics_results + aggregate
GET /analytics/{store_id}/zones     -> query zone_traffic aggregations
GET /analytics/{store_id}/traffic   -> query headcount_trend data
```

Add new endpoints:
```
GET  /analytics/{store_id}/flow          -> flow matrix
GET  /analytics/{store_id}/heatmap       -> aggregated heatmap image
POST /analytics/{store_id}/pos/upload    -> POS CSV upload
GET  /analytics/{store_id}/pos/correlation -> sales-traffic correlation
```

---

## New Schemas to Add

**File:** `services/iep4-analytics/app/schemas.py`

```python
class FlowMatrix(BaseModel):
    matrix: Dict[str, Dict[str, int]]
    top_paths: List[List[str]]

class POSUploadResponse(BaseModel):
    rows_imported: int
    errors: List[str]

class CorrelationResult(BaseModel):
    conversion_rate: float
    revenue_per_visitor: float
    correlation_coefficient: float
    buckets: List[Dict]
```

---

## Evaluation Criteria (must pass before M6)

- [ ] Heatmap correctly shows high-traffic areas matching visual inspection
- [ ] Zone traffic counts within +/-5% of manually counted ground truth
- [ ] Flow analysis produces valid zone-to-zone paths
- [ ] Headcount trendlines render correctly with real data
- [ ] POS CSV upload rejects malformed files with clear errors
- [ ] Sales-traffic correlation produces meaningful results
- [ ] Batch jobs complete within limits (30 min daily, 2 hr weekly)
- [ ] All tests pass

## Re-iteration Triggers

- If heatmap noisy: increase grid cell size, apply Gaussian smoothing
- If flow analysis misses transitions: check trajectory continuity from M4
- If POS correlation meaningless: verify time alignment, increase sample size
