<!--
  Rubric: T5 — Tradeoff evidence (5%)
  Required: ≥3 tradeoffs, each with: what was chosen, what was rejected, and evidence.
-->

# Engineering tradeoffs — RetailVision

> For each tradeoff: state what was chosen, what was rejected, why, and provide evidence (benchmark, measurement, or experiment).

## Tradeoff 1: Edge vs. cloud processing

**Decision:** Heavy vision (RT-DETR-x detection, BoTSORT tracking, resnet50_msmt17 ReID) runs on edge; identity reconciliation runs in cloud.

**Alternative considered:** Stream all raw video frames to cloud for centralized processing.

**Why rejected:**
<!-- TODO: Bandwidth cost (MB/s per camera at target_fps), privacy risk, latency -->

**Evidence:**
<!-- TODO: Measured bandwidth at target_fps, cost calculation -->

---

## Tradeoff 2: XACK-before-processing vs. at-least-once delivery

**Decision:** IEP3 acknowledges Redis messages before processing (see ADR-001).

**Alternative considered:** Acknowledge after processing (at-least-once guarantee).

**Why rejected:**
At-least-once delivery requires full reconciliation idempotency on replay.
Reconciliation creates `global_id` UUIDs, links them to `local_id`s, writes
canonical floor trajectories, and transitions FSM states. Making all of this
replay-safe requires either (a) deterministic `global_id` derivation from
batch content — complex and fragile — or (b) storing every processed
`batch_key` to detect replays — adds a write per batch, a table to maintain,
and a new failure mode when the replay-detection state diverges from the
reconciliation state. The complexity is disproportionate to the benefit for
the expected crash frequency (rare; k3s + systemd restart policies cover the
common case).

**Evidence (ADR-001 failure mode analysis):**

| Crash timing | Redis state | DB state | Footprint |
|---|---|---|---|
| After XACK, before `on_ready` fires | message gone | nothing written | None — clean failure |
| Inside reconciliation transaction, before COMMIT | message gone | PostgreSQL MVCC rollback | None — atomic rollback |
| After COMMIT, before `process_batch` returns | message gone | all writes committed | None — full success |
| `global_identity` created, crash before `global_tracking_history` written | message gone | partial commit | **Orphan** — handled by `orphan_sweep()` |

The only real orphan scenario is an extremely narrow window. The orphan sweep
(`run_orphan_sweep()`) runs unconditionally on every IEP3 startup and every 50
batches thereafter, targeting exactly this case.

---

## Tradeoff 3: Fixed 60 s window vs. continuous streaming reconciliation

**Decision:** Fixed windowed batches — all cameras synchronize to wall-clock-aligned
60-second boundaries before IEP3 runs (see ADR-003).

**Alternative A considered:** Real-time stateful stream joining across N camera
streams (Flink-style windowed joins with watermarks).

**Why A rejected:**
Requires distributed state management (per-camera watermarks, late-arrival
handling, out-of-order event buffering), ordering guarantees across streams,
and a stateful streaming framework — disproportionate complexity for a retail
analytics use case that does not need sub-minute resolution. The operational
surface (managing a Flink/Spark cluster at the edge) would dominate the
engineering budget.

**Alternative B considered:** Per-frame reconciliation (IEP3 runs after every
frame from every camera).

**Why B rejected:** O(frames × cameras) reconciliation invocations per second.
At 5 FPS × 10 cameras = 50 IEP3 invocations/second, each with a PostgreSQL
transaction. Write amplification makes this impractical on a shared database.

**Evidence:**
Retail analytics requires 1-minute granularity for dwell time, occupancy, and
flow metrics — sub-minute data adds no analytical value and significantly
increases operational cost. Maximum analytics latency of ~60 s is explicitly
acceptable for the use case. All IEP2 instances share wall-clock-aligned window
boundaries (governed by APScheduler + `store_operating_hours`), so the
synchronization barrier is zero-cost.

---

## Tradeoff 4: ReID threshold — conservative 0.85 vs. proxy-better 0.75

**Decision:** `reid_fallback_threshold = 0.55` in IEP3's 3-stage matcher.
For the standalone `LocalIdentityManager` (per-camera), `reid_threshold = 0.85`
(production default for the resnet50_msmt17 model).

**Alternatives tested:** 0.75, 0.80, 0.85, 0.90 — threshold sweep on resnet50_msmt17
(MLflow experiment `reid`, 4 runs, `clip_cashier.mp4`, 16 people, 1810 frames).

**Evidence (REID_RESULTS.md §2):**

| reid_threshold | count_error ↓ | match_rate ↑ | avg_recovery_sim |
|---|---|---|---|
| 0.75 | **8** | **0.71** | 0.91 |
| 0.80 | 10 | 0.69 | 0.92 |
| **0.85 (production)** | 18 | 0.60 | 0.93 |
| 0.90 | 32 ❌ | 0.43 ❌ | 0.95 |

**Decision rationale:**
0.75 is proxy-better — it reduces count_error from 18 to 8 and raises match_rate
from 0.60 to 0.71. However, all these metrics are *proxy* metrics: there is no
per-person identity ground truth for the test clip (we know 16 people total, not
"who is who when"). The extra recoveries at 0.75 have high average similarity
(0.91) — reassuring — but without labelled data we cannot confirm they are not
false merges (two different people merged into one `global_id`).

0.85 is the conservative production choice: it is promoted in the MLflow registry
as `retailvision-reid v1 Production`. The 0.75 finding is a documented tuning
insight — validate with a labelled clip before changing production.

0.90 is decisively eliminated (count_error 32, match_rate 0.43 — the system
fails to recover most returning people).

---

## Tradeoff 5: Detection model selection

**Decision:** RT-DETR-x (`conf=0.5`, `imgsz=640`) — transformer-based detector, TensorRT FP16 on Jetson.

**Alternatives tested:** yolov8n, yolov8x, yolov9c, yolo11m, yolo11x-seg, yolo11x-pose, yolo12m (6 rounds, 24 MLflow runs — see `docs/docs_models/detection/`)

**Why RT-DETR-x chosen:**

| Dimension | RT-DETR-x | Best YOLO alternative |
|---|---|---|
| Avg detection confidence | **85.6%** | yolov8x 81.4% |
| Peak count error (crowded) | **1** | yolov8x / yolo11x-seg: 1 (tied) |
| Mannequin false positives | **0** | yolov8x: 2,953 — fails |
| ID switches (crowded) | 7 | yolov8x: 16 |

RT-DETR-x is the only model that simultaneously achieves near-perfect people detection and zero mannequin false positives. YOLO11n is the low-compute fallback when edge throughput is constrained (nano model, higher threshold accepts lower recall).
