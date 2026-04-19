# Milestone 1: Project Setup & Infrastructure Foundation

**Duration:** 1 week
**Dependencies:** None
**Goal:** Repository structure, development environment, Docker setup, database schemas, and basic FastAPI skeleton for all services.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| GitHub repo + branching | DONE | main, development, feature branches |
| Directory structure | DONE | All 6 services, frontend, prompts, tests, infra dirs exist |
| FastAPI skeletons + /health | DONE | All 6 services respond to /health |
| Pydantic API contracts | DONE | schemas.py in IEP1-5, EEP models |
| PostgreSQL schema + Alembic | PARTIAL | See gap list below |
| Redis connection module | DONE | sync + async clients in IEP2, EEP |
| Dockerfiles + docker-compose | DONE | 13 containers orchestrated |
| GitHub Actions CI | PARTIAL | Runs EEP tests + frontend build, missing linting |
| Unit tests for schemas | PARTIAL | tests/unit/test_schemas.py exists |

**Overall: ~85% complete**

---

## Remaining Tasks

### 1. Complete Database Schema

Add missing tables via a new Alembic migration (`003_missing_tables`):

**File:** `services/eep/migrations/versions/003_missing_tables.py`

```
Tables to add:
- employees (id, store_id, name, role, reid_embedding BYTEA, enrolled_at, updated_at)
- shifts (id, employee_id, store_id, start_time, end_time, created_at)
- tracking_history (id, store_id, camera_id, person_id, zone_name, entered_at, exited_at, dwell_seconds)
- alerts (id, store_id, rule_id, type, severity, status, message, data JSONB, created_at, resolved_at)
- pos_transactions (id, store_id, transaction_id, amount, items_count, timestamp, zone_name)
- analytics_results (id, store_id, type, period_start, period_end, data JSONB, created_at)
```

**Existing tables (already created):**
- stores, floor_plans, zones, obstacles, cameras, calibrations, tracking_results

### 2. Add Linting to CI

**File:** `.github/workflows/ci.yml`

Add a lint job:
```
- flake8 across all services/
- black --check across all services/
- eslint on frontend/src/
```

### 3. Expand Unit Tests

**File:** `tests/unit/test_iep_schemas.py`

Write tests for:
- IEP1 schemas (VideoUploadResponse)
- IEP2 schemas (TrackingStartRequest, TrackingProgressResponse, TrajectoryResponse)
- IEP3 schemas (AlertRuleCreate, AlertRule, TrackingEvent, AlertResult, Alert)
- IEP4 schemas (TrackingSnapshot, StoreSummary, ZoneAnalytics, TrafficTimeSeries)
- IEP5 schemas (AgentQuery, AgentResponse, ReportRequest, ReportResponse, Suggestion)

### 4. Redis Key Naming Conventions

**File:** `services/eep/app/core/redis_client.py` (or shared module)

Document and enforce key patterns:
```
tracking:job:{camera_id}          -- tracking job state (exists)
person:store:{store_id}:{pid}     -- real-time person record (M4)
alert:store:{store_id}:{alert_id} -- active alerts (M4)
analytics:cache:{store_id}:{key}  -- cached analytics (M5)
```

---

## Evaluation Criteria (must pass before M2)

- [ ] All 6 services start via `docker compose up` and respond to `GET /health` with 200
- [ ] PostgreSQL has ALL tables (including employees, shifts, alerts, etc.) created via Alembic
- [ ] Redis connection works: basic set/get from EEP and IEP2
- [ ] S3 bucket `retailvision` exists, test upload/download succeeds
- [ ] GitHub Actions CI runs lint + tests on PR to development
- [ ] All unit tests pass

## Re-iteration Triggers

- If Docker containers fail to communicate: check `docker compose` networking, ensure all services on same default network
- If schema issues discovered later: add new Alembic migration, never edit existing ones
- If CI is flaky: check service health waits, add retry logic to smoke tests
