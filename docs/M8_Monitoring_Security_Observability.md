# Milestone 8: Monitoring, Observability & Security

**Duration:** 1 week
**Dependencies:** M4
**Goal:** Comprehensive Prometheus metrics, Grafana dashboards, rate limiting, API authentication, and error handling across all services.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Prometheus deployment | DONE | Container running, scraping EEP + IEP1 + IEP2 |
| Grafana deployment | DONE | Container running, basic dashboard |
| cAdvisor | DONE | Container metrics |
| EEP auto-instrumentation | DONE | prometheus-fastapi-instrumentator |
| IEP1 custom metrics | DONE | video_uploads, upload_bytes, duration, frame_extraction |
| IEP2 custom metrics | DONE | tracking_jobs, duration, frames, detections, active_jobs |
| IEP3-5 Prometheus scraping | NOT DONE | Commented out in prometheus.yml |
| IEP3-5 custom metrics | NOT DONE | |
| Grafana ML-specific dashboards | NOT DONE | Only basic request/error/latency panels |
| Rate limiting | NOT DONE | |
| API key authentication | NOT DONE | |
| Error handling standardization | NOT DONE | |
| Redis snapshot to PostgreSQL | NOT DONE | |

**Overall: ~40% complete** (infrastructure exists, needs expansion)

---

## Implementation Tasks

### 1. Enable Prometheus Scraping for IEP3-5

**File:** `monitoring/prometheus.yml`

Uncomment and add scrape targets:
```yaml
- job_name: 'iep3-alerts'
  static_configs:
    - targets: ['iep3-alerts:8003']
  metrics_path: /metrics

- job_name: 'iep4-analytics'
  static_configs:
    - targets: ['iep4-analytics:8004']
  metrics_path: /metrics

- job_name: 'iep5-agent'
  static_configs:
    - targets: ['iep5-agent:8005']
  metrics_path: /metrics
```

Add `prometheus-fastapi-instrumentator` to IEP3-5 requirements.txt and wire up in each main.py.

### 2. Custom Metrics per Service

**IEP3 metrics** (`services/iep3-alerts/app/core/metrics.py`):
```
alerts_fired_total (counter, labels: type, severity)
alert_evaluation_duration (histogram)
active_rules_total (gauge)
alert_acknowledged_total (counter)
```

**IEP4 metrics** (`services/iep4-analytics/app/core/metrics.py`):
```
analytics_ingest_total (counter)
analytics_ingest_duration (histogram)
batch_job_duration (histogram, labels: job_type)
batch_job_failures_total (counter, labels: job_type)
heatmap_generation_duration (histogram)
pos_uploads_total (counter)
```

**IEP5 metrics** (`services/iep5-agent/app/core/metrics.py`):
```
agent_queries_total (counter)
agent_query_duration (histogram)
llm_call_duration (histogram, labels: provider)
llm_tokens_used (counter, labels: provider, direction=[input,output])
llm_fallback_total (counter)
hallucination_detected_total (counter)
tool_call_total (counter, labels: tool_name)
tool_call_duration (histogram, labels: tool_name)
report_generation_total (counter, labels: type)
```

**IEP2 additional metrics**:
```
reid_cosine_distance (histogram)   -- for MLOps rollback detection
detection_confidence (histogram)   -- YOLO confidence distribution
track_fragmentation_rate (gauge)   -- ID switches per 100 frames
```

### 3. Grafana Dashboards

**File:** `monitoring/grafana/dashboards/` — add/update JSON dashboard files:

#### Dashboard 1: System Overview
```
Panels:
- Service health (up/down for all 6 services)
- Request rate per service (stacked bar)
- Error rate per service (5xx)
- P95 latency per service
- Container CPU/memory (cAdvisor)
- Redis memory usage
- PostgreSQL connection count
```

#### Dashboard 2: Vision Pipeline
```
Panels:
- Active tracking jobs (gauge)
- Tracking job duration (histogram)
- Frames processed per second
- Detection confidence distribution
- ReID cosine distance distribution
- Track fragmentation rate
- Heatmap generation success/fail
- GPU utilization (if available)
```

#### Dashboard 3: Alerts Service
```
Panels:
- Alerts fired over time (by type, severity)
- Alert evaluation latency
- Active rules count
- Alert acknowledgment rate
- Time to acknowledge distribution
```

#### Dashboard 4: Analytics Pipeline
```
Panels:
- Ingestion rate (snapshots/min)
- Batch job status (running/completed/failed)
- Heatmap generation time
- POS uploads
- Analytics query latency
```

#### Dashboard 5: AI Agent
```
Panels:
- Queries per hour
- LLM latency (by provider)
- Token usage (input vs output)
- Fallback rate
- Hallucination detection rate
- Tool call distribution
- Report generation count
```

#### Dashboard 6: Camera Health
```
Panels:
- Frame quality rejection rate per camera
- Frames per second per camera
- Chunk processing status
- Last successful chunk timestamp
```

### 4. Rate Limiting on EEP

**File:** `services/eep/app/middleware/rate_limit.py` (NEW)

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Apply in main.py:
app.state.limiter = limiter

# Rate limits:
#   - General API:        100 req/min per IP
#   - Video upload:       10 req/min per IP
#   - Tracking start:     20 req/min per IP
#   - Agent query:        30 req/min per IP
```

Add `slowapi` to `services/eep/requirements.txt`.

### 5. API Key Authentication

**File:** `services/eep/app/middleware/auth.py` (NEW)

```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    """Validate API key against database.

    Keys stored in PostgreSQL: api_keys (id, key_hash, name, created_at, last_used)
    Hash with bcrypt.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa.text("SELECT id FROM api_keys WHERE key_hash = :hash"),
            {"hash": bcrypt.hash(api_key)}
        )
        if not result.first():
            raise HTTPException(401, "Invalid API key")

# Add as dependency to protected routes
# Health and metrics endpoints remain public
```

**Migration:** Add `api_keys` table.

### 6. Standardized Error Handling

**File:** `services/eep/app/middleware/error_handler.py` (NEW)

```python
@app.exception_handler(Exception)
async def global_error_handler(request, exc):
    """Consistent error response format across all endpoints.

    Response: {
        "error": str,
        "detail": str,
        "status_code": int,
        "request_id": str  # for tracing
    }
    """

# Error scenarios to handle:
# - Camera disconnect: return 503 with retry-after header
# - Model crash: restart tracker thread, return 500 with error detail
# - Redis outage: fallback to degraded mode, log warning
# - LLM timeout: fallback provider, then 503
# - Chunk processing failure: retry once, then alert
# - S3 unavailable: queue uploads, retry with backoff
```

Apply same pattern to IEP1-5.

### 7. Redis Snapshot to PostgreSQL

**File:** `services/eep/app/utils/redis_snapshot.py` (NEW)

```python
async def snapshot_redis_to_db():
    """Periodic backup of volatile Redis state to PostgreSQL.

    Runs every 5 minutes:
    1. Export all person:{store_id}:* keys
    2. Export all tracking job states
    3. Write to redis_snapshots table (timestamp, data JSONB)
    4. Keep last 24 hours of snapshots

    Recovery:
    - On Redis restart, restore latest snapshot
    """
```

---

## Evaluation Criteria (must pass before M9)

- [ ] Prometheus scrapes metrics from ALL 6 services
- [ ] All 6 Grafana dashboards render with real data
- [ ] Rate limiting returns 429 on excess requests
- [ ] API key auth returns 401 on invalid key
- [ ] Each error scenario produces correct fallback behavior
- [ ] Redis snapshot/restore cycle works correctly
- [ ] All custom metrics are populated and visible

## Re-iteration Triggers

- If metrics missing: check Prometheus scrape config, verify /metrics endpoint responds
- If dashboards empty: check datasource config, verify metric names match queries
- If rate limiting too aggressive: adjust limits based on load testing
