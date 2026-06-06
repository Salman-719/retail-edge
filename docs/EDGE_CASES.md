<!--
  Rubric: T6 — Execution quality and edge cases (5%), S3 — Errors/timeouts/retries/fallbacks (3%)
-->

# Edge cases and failure modes — RetailVision

## 1. Failure scenario catalogue

| Scenario | Component affected | Behavior | Recovery mechanism | Test coverage |
|---|---|---|---|---|
| RTSP feed drops mid-window | IEP1 | TODO | TODO | TODO |
| IEP3 crashes mid-batch | IEP3 | Rolls back via XACK model; orphan sweep on restart | ADR-001, orphan sweep runbook | TODO |
| Two persons with similar embeddings (false merge risk) | IEP3 | Cosine threshold prevents merge if score < threshold | Threshold tuning (TRADEOFFS.md §4) | TODO |
| Camera never sends batch_complete in window | IEP3 | TODO: timeout behavior | TODO | TODO |
| YOLO service (ZMQ) unavailable | IEP2 | TODO: retry N times, then? | TODO | TODO |
| OSNet service (ZMQ) unavailable | IEP2 | TODO | TODO | TODO |
| Edge Redis unavailable | IEP1 / IEP2 | TODO | TODO | TODO |
| Edge device loses power | Edge Agent | TODO: gRPC stream reconnect on restore | TODO | TODO |
| EEP → Edge Agent gRPC call fails | EEP | TODO: retry + alert | TODO | TODO |
| PostgreSQL unavailable | EEP / IEP3 | TODO | TODO | TODO |
| MinIO unavailable | IEP2 (frame storage) | TODO | TODO | TODO |
| Malformed payload to EEP | EEP | 422 Unprocessable Entity (Pydantic) | Input validation | tests/e2e/ |

## 2. Resilience design

### Redis consumer group crash safety
<!-- TODO: Explain XREADGROUP + XACK model, how pending-entries list works, orphan sweep -->

### k3s restart policies
<!-- TODO: Which services have restart: always, on-failure — and why -->

### IEP3 orphan sweep
<!-- TODO: What it does, when it runs, what "orphan" means in this context -->
See `docs/operations/` for the runbook.

## 3. Test coverage for edge cases
<!-- TODO: For each row in the table above, link to the specific test file/function that covers it -->
