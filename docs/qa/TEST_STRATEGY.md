<!--
  Rubric: Q1 — Test suite breadth (2.5%)
-->

# Test strategy — RetailVision

## 1. Test pyramid

| Layer | Location | Requires infra? | What it covers |
|---|---|---|---|
| Unit | `tests/unit/` | No | Per-service logic (7 services + mlops + consistency) — see breadth table below |
| Integration | `tests/e2e/` | Yes (Docker Compose) | IEP1→IEP2→IEP3 pipeline with test video clip, Redis consumer groups, PostgreSQL writes |
| End-to-end | `tests/e2e/test_cloud.py` | Yes (live cloud) | Fires against public cloud URL, asserts EEP responds correctly and global_ids are created |

### Unit test breadth

| Service / area | Test files | What is covered |
|---|---|---|
| IEP3 reconciliation | `test_spatial_voter.py`, `test_appearance_fallback.py`, `test_camera_graph.py`, `test_state.py`, `test_selector.py` | SpatialVoter vote accumulation and thresholds; ReidMatcher appearance fallback; camera-graph edge cases; FSM state transitions (ACTIVE→LOST→EXITED→ACTIVE); batch selector logic |
| EEP control plane | `test_schemas.py`, `test_ratelimit.py`, `test_error_envelope.py`, `test_boundary.py`, `test_audit_actions.py`, `test_shadow.py`, `test_canary.py`, `test_resilience.py`, `test_camera_coverage.py` | Pydantic schema validation; rate limiting (429 envelope, Retry-After header, 413 body size); error envelope format; input boundary conditions; audit action validation (CAT A/B1); shadow deployment logic; canary evaluation; EEP resilience behaviors; camera coverage checks |
| IEP2 vision | `test_gallery.py`, `test_inference_deadline.py` | LocalIdentityManager embedding gallery (quality ranking, TTL, heap packing); YOLO/ReID ZMQ deadline/timeout behavior |
| IEP1 ingestion | `test_window.py` | Window manifest construction, boundary alignment, partial-window handling |
| IEP4 alerts | `test_delivery_timeout.py` | Alert delivery timeout and retry behavior |
| IEP5 analytics | `test_metrics_push.py` | End-of-shift analytics metrics computation and push |
| MLOps | `test_promote.py` | Promotion gate threshold evaluation (`check_promotion.py` logic) for all three experiments |
| Cross-service consistency | `test_consistency.py` | Schema and contract consistency checks across service boundaries |

## 2. How to run

```bash
# All unit tests (no infra needed)
pytest tests/unit/ -v

# Integration tests (Docker Compose stack must be running)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
pytest tests/e2e/ -v

# End-to-end against live cloud (requires CLOUD_URL env var)
CLOUD_URL=https://TODO pytest tests/e2e/test_cloud.py -v --cloud
```

## 3. CI integration

All unit and integration tests run automatically on every PR via `.github/workflows/ci.yml`.
The E2E cloud test is run manually before submission.

## 4. Perturbation tests

| Test | What it does | Expected behavior |
|---|---|---|
| Corrupted frame | Send a black/zero frame to IEP2 | IEP2 emits error event, does not crash |
| Malformed JSON to EEP | Send invalid payload to POST /stores | 422 response, not 500 |
| RTSP connection drop | Simulate RTSP disconnect mid-window | IEP1 retries, emits partial manifest |
| TODO | TODO | TODO |

## 5. Test coverage targets

<!-- TODO: What is the current pytest coverage %? Run: pytest --cov=services tests/unit/ -->
