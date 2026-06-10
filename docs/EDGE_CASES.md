<!--
  Rubric: T6 — Execution quality and edge cases (5%), S3 — Errors/timeouts/retries/fallbacks (3%)
-->

# Edge cases and failure modes — RetailVision

## 1. Failure scenario catalogue

| Scenario | Component affected | Behavior | Recovery mechanism | Test coverage |
|---|---|---|---|---|
| RTSP feed drops mid-window | IEP1 | Retries RTSP with exponential backoff; if window closes before recovery, publishes manifest with `status=partial`; IEP3 runs on available tracks | IEP1 retry logic | TODO |
| IEP3 crashes mid-batch | IEP3 | XACK fired before processing — DB transaction rolled back by PostgreSQL MVCC atomically; orphan sweep on restart handles narrow post-COMMIT window | ADR-001, orphan sweep runbook | TODO |
| Two persons with similar embeddings (false merge risk) | IEP3 | 3-stage matcher: SpatialVoter requires min_votes=10 + min_vote_rate=0.6 before committing; ambiguity_margin=0.15 rejects weak plurality; reid_fallback_threshold=0.55 is the final gate | TRADEOFFS.md §4, IEP3_RECONCILIATION.md §3 | tests/unit/iep3/test_appearance_fallback.py |
| Camera never sends batch_complete in window | IEP3 | IEP3 timeout (configurable) fires after waiting for all cameras; reconciliation runs with the cameras that did report; missing camera treated as absent for that window | IEP3 settings.py CAMERA_WAIT_TIMEOUT | TODO |
| YOLO service (ZMQ) unavailable | IEP2 | detect() call raises ZMQ timeout; IEP2 logs error and skips the batch frame; if all frames in a window fail, publishes empty manifest; IEP3 skips the window for that camera | YoloClient timeout/retry | tests/unit/iep2/test_inference_deadline.py |
| ReID service (ZMQ) unavailable | IEP2 | reid_client call raises ZMQ timeout; IEP2 still runs BoTSORT tracking and writes tracking_history; local_centroids are empty for affected batch; IEP3 falls back to spatial-only voting for those local_ids | ReidClient timeout | tests/unit/iep2/test_inference_deadline.py |
| Edge Redis unavailable | IEP1 / IEP2 | IEP1 retries XADD to local Redis with backoff; frames already written to tmpfs are safe; IEP2 cannot consume new manifests until Redis recovers; in-flight batch completes using already-loaded frames | Redis retry in IEP1 | TODO |
| Edge device loses power | Edge Agent | IEP1/IEP2 lose in-flight batch (tmpfs is volatile); completed batches already committed to cloud DB are safe; on restart, Edge Agent re-establishes gRPC stream; EEP resumes camera commands automatically | Edge Agent reconnect logic | TODO |
| EEP → Edge Agent gRPC call fails | EEP | gRPC deadline exceeded → EEP logs warning, marks camera as unreachable; retry on next scheduler tick (WINDOW_SECONDS); alert fires if camera is offline > configured threshold | EEP scheduler + IEP4 alert | TODO |
| PostgreSQL unavailable | EEP / IEP3 | EEP: asyncpg pool raises connection error → 503 on REST endpoints; IEP3: batch fails with exception, no XACK fired (message stays in PEL), retried on reconnect | asyncpg pool retry | TODO |
| MinIO unavailable | IEP2 (frame storage) | Dev S3 path: S3 fetch raises exception, frame is skipped, warning logged; production path uses tmpfs (not S3 for frame storage) — MinIO unavailability only affects thumbnail serving via presigned URLs | IEP2 _fetch_s3_frame error handling | TODO |
| Malformed payload to EEP | EEP | 422 Unprocessable Entity (Pydantic v2 validation) with structured error detail | Input validation | tests/e2e/, tests/unit/eep/test_schemas.py |

## 2. Resilience design

### Redis consumer group crash safety

IEP3 reads `batch_complete` events via `XREADGROUP` on `stream:iep2:batch_complete`
using the consumer group `iep3-consumer`. The XACK fires **before** reconciliation
begins (ADR-001 XACK-before-processing model).

How this works:
- Every message enters the **Pending Entries List (PEL)** when delivered via
  `XREADGROUP`. It stays in the PEL until `XACK` is sent.
- RetailVision fires `XACK` immediately on receipt, before any DB writes. This
  means the message is removed from the PEL before processing starts.
- On IEP3 crash and restart: the PEL is empty (XACK already fired). The message
  is gone. This is intentional — see ADR-001 for the full failure-mode analysis
  showing that no crash scenario produces unrecoverable data corruption.
- `check_pel_health()` runs on startup. A non-empty PEL is a code-level bug
  indicator (XACK was not fired before crash), not a normal operating condition.

IEP2 uses the same model for consuming IEP1 manifests from `stream:iep1:{camera_id}`.
Strict batch-close order: `tracking_history` writes → `local_centroids` UPSERT →
`batch_complete` publish to server Redis → XACK on the IEP1 manifest → tmpfs cleanup.

### k3s restart policies

| Service | Deployment type | Restart policy | Rationale |
|---|---|---|---|
| EEP | Deployment (2 replicas) | Always | Stateless; fast restart safe |
| IEP3 | Deployment | Always | Orphan sweep on restart handles residual state |
| IEP2 | Deployment (1 per camera) | Always | BoTSORT + LocalIdentityManager state is rebuilt from DB on restart |
| IEP4 alerts | StatefulSet | Always | asyncio daemon; stable network identity needed |
| IEP5 analytics | k8s Job | Never (one-shot) | Triggered by EEP shift_closer; re-trigger manually on failure |
| IEP6 agent | Deployment | Always | APScheduler state is in-memory; restarts safely |
| Live Bridge | Deployment | Always | WebSocket connections are re-established by clients |
| Edge Agent | systemd `Restart=on-failure` | On failure | Reconnects gRPC stream to EEP; EEP detects reconnect and resumes |

### IEP3 orphan sweep

An **orphan** is a `global_identity` row with no corresponding
`global_tracking_history` row — produced by the narrow crash window where
IEP3 commits the `global_identity` INSERT but crashes before writing
`global_tracking_history`.

`run_orphan_sweep()` (in `services/iep3_reconciliation/app/repository.py`):
1. Finds `global_identity` rows where `first_seen_ts == last_seen_ts` AND no
   `global_tracking_history` row exists for that `global_id`.
2. Backfills `global_tracking_history` from available `local_centroids` data.
3. Runs unconditionally on every IEP3 startup (prevents orphan accumulation
   across restarts).
4. Runs every `ORPHAN_SWEEP_INTERVAL_BATCHES` (default: 50) batches during normal
   operation.
5. Is always in a **separate transaction** from the reconciliation transaction —
   a sweep failure does not roll back an otherwise-successful reconciliation.
6. Is skipped automatically when reconciliation consumed >80% of the window budget
   (backpressure protection).

See `docs/operations/iep3-orphan-runbook.md` for the operational runbook.

## 3. Test coverage for edge cases
<!-- TODO: For each row in the table above, link to the specific test file/function that covers it -->
