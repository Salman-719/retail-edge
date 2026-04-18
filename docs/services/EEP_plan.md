# EEP — External-Edge Platform (Gateway)

**Role:** Single entry point for the frontend. Owns the relational store (stores, floor plans, zones, cameras, employees, POS), authenticates callers, proxies domain requests to the IEPs, and orchestrates multi-service workflows (onboarding, chunk pipeline).

**Source:** `services/eep/`
**Primary port:** 8000
**Dependencies:** PostgreSQL, Redis, S3, IEP1–IEP5

---

## Contract (what EEP exposes)

| Area | Route | Status |
|------|-------|--------|
| Health | `GET /health` | DONE |
| Stores | `POST/GET/PATCH/DELETE /api/stores[...]` | DONE |
| Floor plans | `POST/GET /api/stores/{sid}/floor-plans` | DONE |
| Zones | `POST/GET/PATCH/DELETE /api/stores/{sid}/zones[...]` | DONE (overlap validation DONE) |
| Obstacles | `POST/GET /api/stores/{sid}/obstacles` | DONE |
| Cameras | `POST/GET/PATCH/DELETE /api/stores/{sid}/cameras[...]` | DONE |
| Calibration | `POST/GET /api/cameras/{cid}/calibration` | DONE |
| Employees | `POST/GET/PATCH/DELETE /api/stores/{sid}/employees[...]` | DONE |
| Shifts | `POST/GET /api/stores/{sid}/employees/{eid}/shifts` | DONE |
| Alerts proxy (→ IEP3) | `GET /api/alerts/{sid}`, `POST /api/alerts/rules`, `PATCH /api/alerts/{aid}` | NOT STARTED |
| Analytics proxy (→ IEP4) | `GET /api/analytics/{sid}/{summary|zones|traffic|flow|heatmap}`, `POST /api/analytics/{sid}/pos/upload` | NOT STARTED |
| Agent proxy (→ IEP5) | `POST /api/agent/query`, `POST /api/agent/report`, `GET /api/agent/suggestions/{sid}` | NOT STARTED |

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| FastAPI skeleton + `/health` | DONE | |
| Async SQLAlchemy engine + session | DONE | `services/eep/app/core/database.py` |
| Alembic migrations 001, 002, 003 | DONE | pos_transactions added in 003 |
| Store / floor plan / zone / obstacle / camera / calibration CRUD | DONE | |
| Employee + shift CRUD | DONE | `app/api/employees.py`, schemas in `app/schemas/employee.py` |
| Zone overlap validation (Shapely) | DONE | `_check_zone_overlap()` in `app/api/zones.py`, returns 409 |
| Redis client (sync + async) | DONE | `app/core/redis_client.py` |
| Redis key naming conventions | DONE | `app/core/redis_keys.py` |
| IEP URL config (IEP1-5) | DONE | `app/core/config.py` |
| Proxy routes to IEP3 / IEP4 / IEP5 | NOT STARTED | M4, M5, M6 wire-up |
| Orchestrator / state machine (chunk pipeline) | NOT STARTED | M4 |
| Rate limiting (slowapi) | NOT STARTED | M8 |
| API key auth middleware | NOT STARTED | M8 |
| Standardised error handler | NOT STARTED | M8 |
| Redis → Postgres snapshot | NOT STARTED | M8 |
| Prometheus auto-instrumentation | DONE | `prometheus-fastapi-instrumentator` |

**Overall: ~60% of EEP scope complete.**

---

## Remaining Tasks

### 1. Proxy routes to IEP3 / IEP4 / IEP5

**File:** `services/eep/app/api/proxy.py` (NEW)

The frontend only talks to EEP. Thin `httpx.AsyncClient` proxies:

```
# Alerts (IEP3)
GET   /api/alerts/{store_id}             -> IEP3_URL + /alerts/{store_id}
POST  /api/alerts/rules                  -> IEP3_URL + /alerts/rules
PATCH /api/alerts/{alert_id}             -> IEP3_URL + /alerts/{alert_id}

# Analytics (IEP4)
GET   /api/analytics/{sid}/summary       -> IEP4_URL + ...
GET   /api/analytics/{sid}/zones
GET   /api/analytics/{sid}/traffic
GET   /api/analytics/{sid}/flow
GET   /api/analytics/{sid}/heatmap
POST  /api/analytics/{sid}/pos/upload    (multipart pass-through)

# Agent (IEP5)
POST  /api/agent/query                   -> IEP5_URL + /agent/query
POST  /api/agent/report
GET   /api/agent/suggestions/{sid}
```

Preserve status code + body, add `X-Proxied-By: eep` response header, log provider latency.

### 2. Orchestrator (chunk-cycle state machine)

**File:** `services/eep/app/api/orchestrator.py` (NEW)

```
POST /api/orchestrator/run
  Input: { store_id, chunk_id, camera_ids }
  Flow:
    1. idle → dispatching : fan-out POST /tracking/start to IEP2 per camera (asyncio.gather)
    2. dispatching → tracking : poll /tracking/progress until all done
    3. tracking → associating : run cross-camera association (IEP2 helper)
    4. associating → alerting : POST /alerts/evaluate to IEP3
    5. alerting → ingesting : POST /analytics/ingest to IEP4
    6. ingesting → done : update Redis person DB, emit completion event
  Output: { chunk_id, status, per_camera_metrics }
```

State persisted under Redis `orchestrator:chunk:{chunk_id}` (TTL 1 h).

### 3. Rate limiting

**File:** `services/eep/app/middleware/rate_limit.py` (NEW)

```
slowapi.Limiter(key_func=get_remote_address)
  - default:          100 req/min
  - /api/.../videos:   10 req/min
  - /tracking/start:   20 req/min
  - /api/agent/query:  30 req/min
```

### 4. API key authentication

**File:** `services/eep/app/middleware/auth.py` (NEW)
**Migration:** add `api_keys` table (id, key_hash, name, created_at, last_used).

```
APIKeyHeader("X-API-Key") → bcrypt hash lookup
- /health and /metrics stay public
- everything under /api requires a valid key
```

### 5. Standardised error handler

**File:** `services/eep/app/middleware/error_handler.py` (NEW)

```
Response shape on any uncaught exception:
  { "error": str, "detail": str, "status_code": int, "request_id": str }

Specific handlers:
  - upstream IEP timeout → 503 with Retry-After
  - Redis outage        → 503, degraded-mode flag
  - S3 unavailable      → 502, queue upload, retry with backoff
```

### 6. Redis → Postgres snapshot

**File:** `services/eep/app/utils/redis_snapshot.py` (NEW)

```
Every 5 min:
  - dump person:{store_id}:* and tracking:job:* keys
  - insert JSONB row into redis_snapshots (timestamp, payload)
  - retain last 24 h

Recovery helper: restore_latest() rehydrates Redis on cold start.
```

---

## Data Model (owned by EEP)

```
stores(id, name, created_at, …)
floor_plans(id, store_id, image_s3_key, scale_m_per_px, …)
zones(id, store_id, name, type, points JSONB, …)
obstacles(id, store_id, name, points JSONB, …)
cameras(id, store_id, name, position_x, position_y, height_meters, rtsp_url?)
calibrations(camera_id, homography_matrix JSONB, reproj_error)
employees(id, store_id, name, role, gallery_embeddings JSON, created_at)
shifts(id, employee_id, start_time, end_time NULL, created_at)
pos_transactions(id, store_id, transaction_id, amount, items_count, timestamp, zone_name)
tracking_results(…)          -- populated by IEP2 callback
tracking_history(…)          -- populated by M4 orchestrator
analytics_results(…)         -- populated by IEP4 (via EEP proxy)
alerts(…)                    -- populated by IEP3
api_keys(id, key_hash, name, created_at, last_used)   -- M8
redis_snapshots(ts, payload JSONB)                    -- M8
```

All schema changes happen via **new Alembic migrations** (never edit existing ones).

---

## Redis Key Conventions (source of truth)

Defined in `services/eep/app/core/redis_keys.py`:

```
tracking:job:{camera_id}              # tracking job state
person:{store_id}:{global_id}         # real-time person record (M4)
carryover:{camera_id}                 # chunk carryover payload (M4)
alert:active:{store_id}:{alert_id}    # unacknowledged alerts
analytics:cache:{store_id}:{key}      # cached analytics (M5)
enrollment:state:{employee_id}        # enrollment job state
orchestrator:chunk:{chunk_id}         # chunk pipeline state (M4)
```

---

## Evaluation Criteria

- [x] `/health` returns 200
- [x] Full onboarding flow (store → zones → cameras → employees) persists and retrieves
- [x] Overlapping zones return 409 with clear error
- [x] Cascade delete removes zones/cameras/employees
- [ ] Proxy routes relay status + body unchanged for IEP3/4/5
- [ ] Orchestrator completes a chunk cycle end-to-end in < 3 min for 8 cameras
- [ ] Rate limiting returns 429 past threshold
- [ ] API key auth returns 401 on invalid key
- [ ] Error handler returns unified shape for every failure mode
- [ ] Redis snapshot/restore round-trips without data loss

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, router registration |
| `app/core/config.py` | Settings (DB URL, Redis URL, IEP1-5 URLs) |
| `app/core/database.py` | Async engine + `AsyncSessionLocal` |
| `app/core/redis_client.py` | Sync + async Redis clients |
| `app/core/redis_keys.py` | Key naming helpers |
| `app/models/*.py` | SQLAlchemy ORM |
| `app/schemas/*.py` | Pydantic request/response |
| `app/api/*.py` | Route modules (stores, zones, cameras, employees, calibration, …) |
| `migrations/versions/*.py` | Alembic migrations (001–003) |

---

## Re-iteration Triggers

- Proxy adds >100 ms overhead → drop to `httpx.AsyncClient(http2=True)` with connection reuse
- Orchestrator timing tight → batch cameras in groups of 4
- Rate limiter too aggressive → raise defaults, add burst allowance
- Redis snapshot OOM → stream keys in chunks of 1000 via `SCAN`
