# IEP4 — Analytics (Batch Aggregation + POS)

**Role:** Consume tracking snapshots from the EEP orchestrator, aggregate into heatmaps / zone traffic / flow matrices / headcount trendlines, ingest and correlate POS data, and serve the analytics endpoints the dashboard uses.

**Source:** `services/iep4-analytics/`
**Primary port:** 8004
**Dependencies:** PostgreSQL (reads `tracking_results`, `tracking_history`, writes `analytics_results`, `pos_transactions`), S3 (heatmap PNGs), APScheduler (batch jobs)

---

## Contract (what IEP4 exposes)

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /health` | Liveness | DONE |
| `POST /analytics/ingest` | Receive `TrackingSnapshot` from orchestrator | DONE (stub, no-op) |
| `GET /analytics/{sid}/summary` | `StoreSummary` for period | DONE (stub) |
| `GET /analytics/{sid}/zones` | `List[ZoneAnalytics]` | DONE (stub) |
| `GET /analytics/{sid}/traffic` | `TrafficTimeSeries` | DONE (stub) |
| `GET /analytics/{sid}/flow` | Zone flow matrix + top paths | NOT STARTED |
| `GET /analytics/{sid}/heatmap` | Aggregated heatmap (S3 URL) | NOT STARTED |
| `POST /analytics/{sid}/pos/upload` | Upload POS CSV (`POSUploadResponse`) | NOT STARTED |
| `GET /analytics/{sid}/pos/correlation` | Sales-vs-traffic correlation | NOT STARTED |
| `GET /metrics` | Prometheus | NOT STARTED |

**Schemas:** `services/iep4-analytics/app/schemas.py` — `TrackingSnapshot`, `StoreSummary`, `ZoneAnalytics`, `TrafficBucket`, `TrafficTimeSeries` (stubs: `FlowMatrix`, `POSUploadResponse`, `CorrelationResult` to be added in M5).

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| FastAPI skeleton + `/health` | DONE | |
| Typed schemas (core) | DONE | |
| Stub endpoints (empty responses) | DONE | |
| Async SQLAlchemy session | NOT STARTED | M5 |
| Ingest handler (real) | NOT STARTED | M5 |
| Heatmap aggregation | NOT STARTED | M5 |
| Zone traffic aggregation | NOT STARTED | M5 |
| Zone-to-zone flow | NOT STARTED | M5 |
| Headcount trendlines | NOT STARTED | M5 |
| People classification (groups / demographics) | NOT STARTED | M5 (stretch) |
| POS upload + parsing | NOT STARTED | M5 |
| POS/traffic correlation | NOT STARTED | M5 |
| APScheduler (hourly/daily/weekly jobs) | NOT STARTED | M5 |
| Custom Prometheus metrics | NOT STARTED | M8 |
| Prometheus scrape target | NOT STARTED | M8 |

**Overall: ~10%.**

---

## Implementation Tasks

### 1. DB session + reads

**File:** `services/iep4-analytics/app/core/database.py` (NEW) — async engine + session.

IEP4 reads:
- `tracking_results` — raw per-job outputs (trajectory JSON, zone_occupancy JSON).
- `tracking_history` — per-person zone enter/exit events (populated by orchestrator in M4).

IEP4 writes:
- `analytics_results(type, period_start, period_end, data JSONB)` — aggregated output.
- `pos_transactions` — rows from CSV uploads.

### 2. Ingest handler

**File:** `services/iep4-analytics/app/api/ingest.py` (NEW)

```
POST /analytics/ingest  (body: TrackingSnapshot)
  1. Parse trajectory
  2. Compute per-zone entry/exit counts (zone membership transitions)
  3. Compute zone-to-zone transitions
  4. Compute headcount at each timestamp bucket
  5. Upsert running hourly + daily aggregates into analytics_results
  6. Return 202
```

### 3. Heatmap aggregation

**File:** `services/iep4-analytics/app/utils/heatmap.py` (NEW)

```
generate_aggregated_heatmap(store_id, start, end) -> s3_key
  - query tracking_results for store × period
  - rasterise trajectory points onto 0.5 m floor grid
  - compute person-seconds / cell
  - render with matplotlib colormap overlay (RGBA transparent)
  - upload: stores/{store_id}/analytics/heatmap_{start}_{end}.png
```

### 4. Zone traffic aggregation

**File:** `services/iep4-analytics/app/utils/zone_traffic.py` (NEW)

Per zone, per bucket (`hour|day|week`):
- `entry_count`, `exit_count`, `avg_dwell`, `peak_occupancy`, `total_visitors`
- Persisted as `analytics_results.type='zone_traffic'`.

### 5. Flow analysis

**File:** `services/iep4-analytics/app/utils/flow.py` (NEW)

```
compute_flow_matrix(store_id, start, end) -> FlowMatrix
  - for each person, derive zone sequence
  - matrix[zone_a][zone_b] = transition count
  - top_paths: top-K most frequent zone sequences
  - sankey_data: {nodes, links} for frontend
```

### 6. Headcount trend

**File:** `services/iep4-analytics/app/utils/headcount.py` (NEW)

Query snapshot history (from `tracking_history` or Redis-dumped analytics_results), bucket by `hour|day`, return `[{timestamp, count}]`.

### 7. People classification (stretch)

**File:** `services/iep4-analytics/app/utils/classification.py` (NEW)

- **Groups:** proximity rule (< 1 m for > 30 s) + co-travel similarity → cluster trackIds.
- **Demographics:** pretrained age/gender estimator (e.g. Insightface). Never train custom.
- Aggregate distributions per zone & time.

### 8. POS

**File:** `services/iep4-analytics/app/api/pos.py` (NEW)

```
POST /analytics/{sid}/pos/upload
  - multipart CSV
  - validate schema: transaction_id, amount, items_count, timestamp, zone_name
  - pandas parse → pos_transactions
  - return {rows_imported, errors[]}

GET /analytics/{sid}/pos/correlation?start&end
  - join pos_transactions with zone_traffic on time bucket
  - compute conversion_rate = transactions / visitors
  - revenue_per_visitor = sum(amount) / visitors
  - Pearson correlation (traffic ↔ revenue) per bucket
  - return CorrelationResult
```

### 9. Batch scheduler

**File:** `services/iep4-analytics/app/scheduler.py` (NEW)

```
APScheduler jobs:
  hourly  @ :05  → zone_traffic aggregation for last hour
  daily   @ 02:00 → heatmap + flow matrix + headcount for previous day
  weekly  @ Sun 03:00 → weekly report + POS correlation
```

Each job writes its result into `analytics_results`; S3 artefacts (heatmaps, charts) cached in `analytics:cache:{store_id}:{key}` Redis keys.

### 10. Wire real endpoints (replace stubs)

**File:** `services/iep4-analytics/app/main.py` — replace placeholder returns with DB queries against `analytics_results`. Add new endpoints (`/flow`, `/heatmap`, `/pos/*`).

### 11. Observability

**File:** `services/iep4-analytics/app/core/metrics.py` (NEW)

```
analytics_ingest_total           Counter
analytics_ingest_duration        Histogram
batch_job_duration               Histogram (job_type)
batch_job_failures_total         Counter (job_type)
heatmap_generation_duration      Histogram
pos_uploads_total                Counter
```

---

## Data Contract (Ingest)

```
POST /analytics/ingest
{
  "store_id": str,
  "camera_id": str,
  "zone_occupancy": { zone_name: { "seconds": float, "percent": float } },
  "trajectory":     [ { frameIdx, x, y, trackId, personType?, employeeId? } ],
  "total_frames": int,
  "fps": float,
  "recorded_at": ISO datetime
}
```

---

## Evaluation Criteria

- [ ] Heatmap visually matches high-traffic areas on sample data
- [ ] Zone traffic counts within ±5 % of manual ground truth
- [ ] Flow matrix produces valid zone sequences
- [ ] Headcount trend renders for real period
- [ ] POS CSV rejects malformed files with row-level errors
- [ ] POS correlation produces meaningful coefficient on sample data
- [ ] Daily batch job finishes < 30 min, weekly < 2 h
- [ ] Prometheus metrics populate

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI + endpoint wiring |
| `app/schemas.py` | Typed I/O |
| `app/api/ingest.py` (NEW) | Real ingest handler |
| `app/api/pos.py` (NEW) | POS upload + correlation |
| `app/utils/heatmap.py` (NEW) | Aggregated heatmap |
| `app/utils/zone_traffic.py` (NEW) | Zone traffic aggregation |
| `app/utils/flow.py` (NEW) | Flow matrix |
| `app/utils/headcount.py` (NEW) | Trend lines |
| `app/utils/classification.py` (NEW, stretch) | Groups + demographics |
| `app/scheduler.py` (NEW) | APScheduler jobs |
| `app/core/database.py` (NEW) | Async DB |
| `app/core/metrics.py` (NEW) | Prometheus |

---

## Re-iteration Triggers

- Heatmap noisy → increase grid cell to 1 m, apply Gaussian smoothing
- Flow misses transitions → verify trajectory continuity (M4 carryover fidelity)
- POS correlation meaningless → check time alignment, require ≥ 1 k samples
- Batch jobs slow → index `analytics_results(store_id, period_start)`, move heavy aggregates to materialised views
