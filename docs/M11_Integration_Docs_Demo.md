# Milestone 11: Integration Testing, Documentation & Demo Preparation

**Duration:** 1 week
**Dependencies:** All previous milestones
**Goal:** Complete test suite, technical documentation, tradeoff evidence, and demo readiness.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Unit tests | PARTIAL | Only test_schemas.py |
| Integration tests | NOT STARTED | |
| E2E tests | NOT STARTED | |
| Stress tests | NOT STARTED | |
| Architecture docs | NOT STARTED | |
| API documentation | PARTIAL | FastAPI auto-generates /docs per service |
| Deployment guide | NOT STARTED | |
| Tradeoff evidence | NOT STARTED | |
| Demo script | NOT STARTED | |

**Overall: ~5% complete**

---

## Implementation Tasks

### 1. Complete Test Suite

#### Unit Tests

**Files:** `tests/unit/`

```
test_schemas.py          -- existing, expand for IEP1-5
test_homography.py       -- homography computation edge cases
test_quality_filters.py  -- blur/dark/frozen detection
test_reid.py             -- embedding extraction, cosine similarity
test_rule_engine.py      -- alert rule evaluation logic
test_analytics.py        -- aggregation computations
test_hallucination.py    -- hallucination detection
test_carryover.py        -- chunk carryover serialization
```

#### Integration Tests

**Files:** `tests/integration/`

```
test_onboarding_flow.py
  1. Create store -> upload floor plan -> draw zones -> register cameras -> calibrate
  2. Verify all entities persist and retrieve correctly
  3. Delete store -> verify cascade

test_iep1_pipeline.py
  1. Upload video -> verify S3 storage -> verify metadata extraction
  2. Test frame quality rejection on known bad frames

test_iep2_pipeline.py
  1. Start tracking job -> poll progress -> verify completion
  2. Check trajectory data format
  3. Verify heatmap generation + S3 upload
  4. Verify zone occupancy computation

test_iep3_alerts.py
  1. Create rules -> send tracking event -> verify alert fires
  2. Verify alert persistence in DB
  3. Test acknowledgment flow

test_iep4_analytics.py
  1. Ingest tracking snapshot -> query summary -> verify aggregation
  2. Test zone traffic computation
  3. Test POS upload + correlation

test_iep5_agent.py
  1. Send query -> verify tool calls -> verify data-grounded answer
  2. Test multi-turn conversation
  3. Test hallucination detection with fabricated response

test_eep_orchestration.py
  1. Full chunk cycle: ingest -> track -> alert -> analytics
  2. Multi-camera association
  3. Person database state verification
```

#### End-to-End Tests

**File:** `tests/e2e/test_full_pipeline.py`

```python
"""Full pipeline test — from store creation to AI agent query.

Prerequisite: All services running (docker compose or EKS).

Steps:
  1. Create store with floor plan, zones, cameras
  2. Upload test video
  3. Run calibration
  4. Start tracking -> wait for completion
  5. Verify tracking results (trajectory, zone occupancy, heatmap)
  6. Verify alerts fired (if rules configured)
  7. Verify analytics ingested
  8. Query AI agent about the store
  9. Verify agent response is data-grounded

Timeout: 10 minutes
"""
```

#### Stress Tests

**File:** `tests/stress/test_sustained_operation.py`

```python
"""Sustained operation test — 30+ minutes of continuous processing.

Process:
  1. Configure 4-8 cameras with test videos
  2. Run consecutive chunk cycles for 30 minutes
  3. Verify:
     - No memory leaks (RSS stays stable)
     - No ID loss accumulation
     - No Redis key explosion
     - Alert system remains responsive
     - Analytics continue to aggregate
  4. Record metrics: throughput, latency percentiles, error rate
"""
```

### 2. Technical Documentation

**File:** `docsme/Architecture_Overview.md` (NEW)

```
Contents:
1. System architecture diagram (ASCII or linked image)
2. Service descriptions (EEP, IEP1-5)
3. Data flow: video upload -> tracking -> alerts -> analytics -> agent
4. Communication patterns (sync HTTP, async events)
5. Storage architecture (PostgreSQL, Redis, S3)
6. Authentication & authorization model
7. Monitoring architecture
```

**File:** `docsme/API_Documentation.md` (NEW)

```
Contents:
- Link to each service's /docs (Swagger UI)
- Cross-service API contracts
- Authentication requirements
- Rate limits
- Error response format
- Webhook payloads
```

**File:** `docsme/Deployment_Guide.md` (NEW)

```
Contents:
1. Local development setup (docker compose)
2. Environment variables reference
3. Database migration steps
4. AWS deployment steps
5. Kubernetes manifest application
6. Monitoring setup
7. Troubleshooting common issues
```

**File:** `docsme/Configuration_Guide.md` (NEW)

```
Contents:
- Environment variables per service
- Feature flags
- Tuning parameters (SAMPLE_EVERY, chunk duration, alert thresholds)
- Model selection (YOLOv8n vs v8s, BoT-SORT config)
- Redis TTL configuration
```

### 3. Tradeoff Evidence

**File:** `docsme/Tradeoffs.md` (NEW)

```
Tradeoff areas with measured evidence:

1. Detection model: YOLOv8n vs YOLOv8s vs RT-DETR
   - Latency benchmarks (ms/frame)
   - mAP comparison on retail footage
   - GPU memory usage
   - Decision: YOLOv8n for speed at acceptable accuracy

2. Tracker: ByteTrack vs BoT-SORT
   - ID-switch rate comparison
   - Latency overhead of appearance features
   - Decision: BoT-SORT for better ReID at minimal cost

3. Micro-batch vs streaming
   - Latency comparison (5-min chunks vs real-time)
   - Resource usage (GPU utilization)
   - Complexity comparison
   - Decision: chunk-based for simplicity, acceptable latency

4. ReID model: OSNet vs FastReID
   - Embedding quality (cosine similarity distributions)
   - Inference time
   - Decision: [to be measured]

5. LLM provider: Claude vs OpenAI
   - Response quality on retail queries
   - Latency comparison
   - Cost per query
   - Decision: Claude primary, OpenAI fallback

6. Storage: PostgreSQL + Redis + S3 vs alternatives
   - Why not TimescaleDB for analytics
   - Redis volatility mitigation strategy
   - S3 for blob storage rationale

Include actual numbers, not just qualitative comparisons.
```

### 4. Demo Preparation

**File:** `docsme/Demo_Script.md` (NEW)

```markdown
# RetailVision AI — Demo Script

Duration: 15-20 minutes

## Scene 1: Store Onboarding (3 min)
1. Create new store "Demo Retail Store"
2. Upload floor plan image
3. Draw 4 zones: Entrance, Electronics, Checkout, Staff Area
4. Place 2 cameras on floor plan
5. Upload sample video for each camera
6. Run calibration (mark correspondence points)
7. Save configuration

## Scene 2: Live Monitoring (3 min)
1. Start tracking on both cameras
2. Show MJPEG streams with detection boxes
3. Show floor plan with live person dots
4. Point out headcount, zone occupancy metrics
5. Show an alert firing (queue crowding in checkout)

## Scene 3: Analytics Dashboard (3 min)
1. Show heatmap overlay on floor plan
2. Show zone traffic chart (which zones are busiest)
3. Show headcount trend over the day
4. Show zone-to-zone flow diagram
5. Upload POS data, show conversion correlation

## Scene 4: AI Agent (3 min)
1. Ask: "How busy was the electronics zone today?"
2. Ask: "Should I add more staff to checkout?"
3. Ask: "Compare this week to last week"
4. Show generated daily report with charts

## Scene 5: MLOps & Monitoring (3 min)
1. Show Grafana system overview dashboard
2. Show vision pipeline performance metrics
3. Show MLflow experiment tracking UI
4. Explain model promotion/rollback flow

## Scene 6: Architecture & Tradeoffs (3 min)
1. Show architecture diagram
2. Explain EEP/IEP service separation
3. Discuss key tradeoffs with measured evidence
4. Show Kubernetes deployment

## Preparation Checklist
- [ ] Test data loaded (2+ hours of tracking data)
- [ ] Alerts rules configured
- [ ] Analytics batch jobs have run
- [ ] AI agent has data to query
- [ ] Grafana dashboards populated
- [ ] All services healthy
```

### 5. README Update

**File:** `README.md` — update with:
```
- Project description
- Architecture overview (link to docs)
- Quick start (docker compose up)
- Service endpoints table
- Environment variables
- Development guide
- Testing guide
- Deployment guide (link to docs)
```

---

## Evaluation Criteria (Demo Readiness)

- [ ] System runs E2E without failure for 30+ consecutive minutes
- [ ] Dashboard displays live monitoring data correctly
- [ ] Analytics display with real accumulated data
- [ ] AI agent responds with data-grounded insights
- [ ] Alert triggers correctly on test scenario
- [ ] All tests pass (unit, integration, E2E)
- [ ] Zero critical bugs
- [ ] Documentation is complete and clear
- [ ] Tradeoffs section has measured evidence (actual numbers)
- [ ] Demo script runs smoothly end-to-end
- [ ] Can answer questions about every design decision

## Re-iteration Triggers

- If E2E test unstable: identify flaky component, add retry/timeout, fix root cause
- If demo scenario weak: record more diverse test footage, add more alert scenarios
- If tradeoffs lack evidence: re-run benchmarks with proper methodology
