<!--
  Rubric: Q1 — Test suite breadth (2.5%)
-->

# Test strategy — RetailVision

## 1. Test pyramid

| Layer | Location | Requires infra? | What it covers |
|---|---|---|---|
| Unit | `tests/unit/iep3/` | No | IEP3 cosine matching logic, identity state machine transitions, orphan sweep logic |
| Integration | `tests/e2e/` | Yes (Docker Compose) | IEP1→IEP2→IEP3 pipeline with test video clip, Redis consumer groups, PostgreSQL writes |
| End-to-end | `tests/e2e/test_cloud.py` | Yes (live cloud) | Fires against public cloud URL, asserts EEP responds correctly and global_ids are created |

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
