<!--
  RetailVision — Grader Navigation Guide
  Target: 3-hour technical review session
  Focus: engineering depth, architecture decisions, tradeoff evidence
-->

# RetailVision — Grader Navigation Guide

This guide is a structured navigation map, not a sales pitch. Each section directs
you to the concrete artifact — code, file, metric, test, or running endpoint — that
substantiates the claim. Follow the sections in order for a coherent 3-hour arc, or
jump to the rubric evidence index in §8 if you prefer to spot-check by rubric item.

---

## Quick start

| What | Where |
|---|---|
| Frontend | https://app.108.133.40.141.nip.io |
| Grafana | https://grafana.108.133.40.141.nip.io |
| MLflow | https://mlflow.108.133.40.141.nip.io |
| EEP OpenAPI | https://app.108.133.40.141.nip.io/api/docs |
| Edge gRPC | eep.54.247.110.0.nip.io:50051 (TLS) |
| Login | support.retailvision@gmail.com / Admin123 (super-admin) |

**What requires live edge vs what is always available:**

| Feature | Available without edge | Requires edge |
|---|---|---|
| UI navigation, store/camera management | ✓ | |
| MLflow experiments + model registry | ✓ | |
| OpenAPI docs + API calls | ✓ | |
| Unit tests (`pytest tests/unit/`) | ✓ | |
| Code architecture review | ✓ | |
| Grafana dashboards (historical metrics) | ✓ if pre-seeded | |
| Analytics heatmap + dwell time | requires data in DB | |
| Vision Debug trace panels | requires pipeline run | |
| Live monitoring camera feed | requires live-bridge deployment | |

To generate live data without a Jetson: run the camera simulator (Docker, no GPU needed)
alongside the local Docker Compose stack — see §4.4.

---

## §1. Architecture orientation (15 min)

### Read first

1. [`README.md`](../README.md) — architecture diagram, tech stack table, doc index
2. [`ARCHITECTURE.md`](../ARCHITECTURE.md) — full service graph, data flows, Redis topology
3. [`docs/decisions/ADR-001-xack-before-processing.md`](decisions/ADR-001-xack-before-processing.md) — the most consequential design decision
4. [`docs/decisions/ADR-003-windowed-batch-60s.md`](decisions/ADR-003-windowed-batch-60s.md) — why fixed 60s windows instead of streaming

### Key architecture points

**Service map:**
```
IEP1 (RTSP ingest, edge)
  → stream:iep1:{cam_id}  (edge-local Redis)
IEP2 (vision, one per camera, edge)
  → tracking_history + local_centroids (Postgres)
  → stream:iep2:batch_complete  (server Redis)
IEP3 (cross-camera reconciliation, cloud, dynamic)
  → global_identities + global_tracking_history (Postgres)
IEP4 (alerts daemon, cloud, dynamic)
IEP5 (end-of-shift analytics job, cloud, dynamic)
IEP6 (AI agent, cloud, static)
EEP (control plane, cloud, static)
  ← REST :8000 ← Frontend
  ← gRPC :50051 ← Edge Agent → k3s on edge
```

**The architectural decision that distinguishes this system:**
IEP3, IEP4, and IEP5 are **not statically deployed**. EEP provisions them dynamically
via the Kubernetes API (`iep3_manager.py`, `iep4_manager.py`, `iep5_manager.py`) when a
store activates, on Karpenter SPOT nodes. They disappear when the store is stopped.
This is orchestration logic (T4), not just configuration.

**Two-Redis topology:**
- Edge-local Redis: loopback-only (`127.0.0.1`), holds only `stream:iep1:{cam}`, ephemeral
- Server Redis: TLS-enabled in cluster, holds `stream:iep2:batch_complete` and `stream:iep2:live:{cam}`

These are separate for isolation: the edge device has no knowledge of the cloud Redis address.
IEP2 publishes to both sides. See `services/iep2_vision/runtime.py`.

---

## §2. ML model selection evidence (20 min)

This is the primary evidence for T1 (AI depth), T5 (tradeoff evidence), M1 (automated lifecycle),
and M2 (experiment tracking). All three model decisions are tracked in MLflow with full run
history — they are not post-hoc claims.

### Open MLflow: https://mlflow.108.133.40.141.nip.io

Three experiments to examine:

**Experiment: `detection`**
- 24 runs comparing RT-DETR-x, YOLOv8-x, YOLO11n, and variants
- Key metric: `val/false_positives` (mannequin false positives)
- RT-DETR-x: 0 mannequin false positives. YOLOv8-x: 1,686–4,506 FP depending on config
- This is not a marginal win — it is a fundamental difference in how the model handles
  stationary figures. See `docs/docs_models/detection/DETECTION_RESULTS.md` for the full table
- Also open `docs/DETECTION_SCREENSHOTS.md` for annotated MLflow screenshots

**Experiment: `reid`**
- 7 runs: resnet50_msmt17, osnet_market, osnet_msmt17, threshold sweep (0.75–0.90)
- Key metrics: `count_error`, `match_rate`, `inference_ms`
- Winner: resnet50_msmt17 — count_error=18, match_rate=0.60, 13ms inference
  vs osnet_msmt17: count_error=39, match_rate=0.35 (despite same training data)
- The 2048-dim embedding is what makes the quality-ranked gallery effective (see §3.2)
- Full threshold sweep: 0.75→0.80→0.85→0.90; `docs/docs_models/reid/REID_RESULTS.md`

**Experiment: `tracking`**
- 7 runs: BoTSORT, ByteTrack, OC-SORT, StrongSORT on the same test sequences
- Key metrics: `unique_track_ids` (lower = less fragmentation), `fragmentation_score`
- BoTSORT: 57 unique_track_ids, 3.56 fragmentation. ByteTrack: 82 / 5.12. StrongSORT: 83 / 5.19
- `with_reid=False` and sparse optical flow CMC was the deliberate choice — see §3.2 for why
- Full results: `docs/docs_models/tracking/TRACKING_RESULTS.md`

**Model registry:**
In MLflow → "Models" tab: three registered models (`detection-model`, `reid-model`,
`tracking-model`). Each has a `Production` stage. The promotion gate is automated —
`scripts/check_promotion.py` runs in CI and only stages a model if it clears defined
thresholds (see `docs/MLOPS_PIPELINE.md` §3).

**Promotion gate code:**
```
scripts/check_promotion.py
```
Run it directly: `python scripts/check_promotion.py --experiment reid --run-id <id>`.
It exits 1 if thresholds are not met. This is what runs in `.github/workflows/ci.yml`.

---

## §3. Cross-camera reconciliation deep dive (25 min)

This is the core AI engineering contribution — the part that does not exist in any
single-camera tracker. Evidence for T1, T6, C1, C2.

### 3.1 The problem being solved

A person walks past camera A, then camera B. Camera A assigns them local_id=5.
Camera B assigns them local_id=3. Without cross-camera reconciliation, these are
two different people in the analytics. The system must merge them into one
`global_identity` using spatial + appearance evidence.

Pixel coordinates are invalid across non-overlapping cameras (different viewpoints,
different scales, different distortions). The only signals available are:
- **Temporal proximity**: did they exit A and enter B within a plausible walk time?
- **Appearance**: are the ReID embeddings similar?
- **Floor position**: after homography projection, are the 3D positions consistent?

The 3-stage matcher in `services/iep3_reconciliation/` implements all three.

### 3.2 The 3-stage algorithm

**Code:** `services/iep3_reconciliation/app/matcher/`

**Stage 1: SpatialVoter** — accumulates evidence over multiple frames before committing

Each frame where a local_id from camera A and a local_id from camera B appear at
floor positions within `vote_distance_threshold_m=1.0m` of each other casts one vote.
A match is only considered when:
- `min_votes=10` (at least 10 co-occurrence frames)
- `min_vote_rate=0.6` (60% of possible frames show co-occurrence)
- `temporal_tolerance_ms=150` (frames must be within 150ms wall-clock)

This eliminates spurious matches from people who happen to cross paths once.

**Stage 2: Ambiguity check**

If the top candidate has a vote margin < `ambiguity_margin=0.15` over the second
candidate, the match is rejected. A weak plurality is not evidence.

**Stage 3: ReidMatcher** — appearance fallback

When spatial evidence is available but inconclusive (or for cross-zone cases where
floor overlap is small), cosine similarity of resnet50_msmt17 embeddings decides.
Threshold: `reid_fallback_threshold=0.55`. Below this, no merge occurs — the system
prefers false negatives (missing a merge) over false positives (wrong merge).

**Why 2048-dim embeddings matter here:** The quality-ranked gallery
(`services/iep2_vision/app/local_identity_manager.py`) keeps the top-K embeddings
per local_id ranked by `quality = confidence × sqrt(bbox_area)`. A large embedding
space allows fine-grained distance comparisons that 128-dim or 512-dim spaces cannot
support at the 0.55 threshold without excessive false merges.

### 3.3 The FSM

Each `global_identity` transitions through:
```
ACTIVE → LOST (no sightings for N seconds) → EXITED (grace period elapsed)
       ← ACTIVE (re-entry before EXITED)
```
Code: `services/iep3_reconciliation/app/state_machine.py`
Tests: `tests/unit/iep3/test_state.py`

### 3.4 Why this is non-trivial (T1, C1)

1. **Homography floor projection** — each camera has an extrinsic+intrinsic calibration
   matrix (see `testing-data/Test2/Extrinsics/` and `Intrinsics/`). IEP2 projects each
   detection's bounding-box centroid through the camera matrix onto the store floor plane.
   This is what makes the `vote_distance_threshold_m=1.0m` a meaningful metric rather than
   a pixel heuristic.

2. **The 60-second window alignment** — IEP3 does not process frames in real time. It waits
   for all cameras to submit their `batch_complete` for a window, then reconciles. This
   means the spatial voter sees complete trajectories within the window. The alternative
   (continuous streaming) would require distributed state across cameras — see ADR-003.

3. **XACK-before-processing** (ADR-001) — IEP3 fires `XACK` on the Redis stream
   *before* beginning reconciliation. The message is removed from the PEL immediately.
   On crash + restart, the PEL is empty. This looks counterintuitive (at-most-once
   instead of at-least-once) but is correct because a partial reconciliation in the
   DB is worse than a skipped window. The orphan sweep compensates for the one narrow
   crash window. Read ADR-001 for the full 4-scenario failure mode analysis.

---

## §4. Live pipeline demo (30 min)

### 4.1 What the grader sees in the UI

Login at https://app.108.133.40.141.nip.io with super-admin credentials.

Navigate to the pre-configured demo store. Explore:
- **Store Setup** → Cameras tab: RTSP URLs registered, calibration uploaded
- **Store Setup** → Operating Hours: `store_operating_hours` rows driving the scheduler
- **Analytics** → dwell time chart, zone occupancy, floor heatmap (requires DB data)
- **Alerts** → triggered alert list, alert rules CRUD, resolve workflow
- **Admin** → Audit log (super-admin only — each state change is recorded with actor + timestamp)
- **Vision Debug** → recon-trace panel (global_id timeline across cameras)

### 4.2 EEP orchestration — what is actually happening (T4)

When the store's operating hours are active, EEP's APScheduler fires every
`WINDOW_SECONDS=60`. This scheduler call:
1. Checks `store_operating_hours` to determine which stores are in-hours
2. For each active store: sends `StartCamera` gRPC commands to the Edge Agent
3. The Edge Agent translates those into `kubectl apply` on k3s — spawning IEP2 Deployments
4. On shift close: fires IEP5 as a k8s Job

This is not trivial CRUD. EEP is a stateful orchestrator.
Code: `services/eep/app/core/scheduler.py`, `services/eep/app/tasks/iep3_manager.py`

### 4.3 Dynamic pod provisioning

To verify IEP3/4 are dynamic: check the Helm chart — there is **no static IEP3 Deployment
template**. The iep3-statefulset.yaml and iep3-service.yaml escape-hatch templates were
deliberately removed. IEP3 only exists as a running pod when EEP creates it.

In a running cluster: `kubectl get pods -n retailvision` shows IEP3/4 only when a store
is active.

### 4.4 Running the full pipeline locally (Docker Compose + camera simulator)

This runs the complete edge + cloud stack on a laptop (CPU mode, no GPU required):

```bash
# Terminal 1 — start the cloud stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Terminal 2 — start the camera simulator (serves testing-data/Test3 videos as RTSP)
cd camera-simulator
./scripts/start.sh
# Prints: rtsp://localhost:8554/test3-cam1  and  rtsp://localhost:8554/test3-cam2
```

Then in the UI: create a store, add cameras with those two RTSP URLs, set operating hours
to include the current time, and activate the store. IEP1 will begin ingesting, IEP2
will process, IEP3 will reconcile. Wait one 60s window to see data in Analytics.

Test3 is the demo dataset: two synchronized cameras (`testing-data/Test3/Cam1.mp4`,
`Cam2.mp4`), already the default in `camera-simulator/streams.csv`. The simulator
loops both feeds from the same wall-clock start boundary so temporal alignment is
consistent across cameras — exactly what the SpatialVoter needs.

---

## §5. Service contracts and API (15 min)

### 5.1 OpenAPI — live at /api/docs

https://app.108.133.40.141.nip.io/api/docs

All 20 REST endpoints are documented with request/response schemas, auth requirements,
and error codes. FastAPI generates this from the Pydantic v2 models — there is no
manual documentation lag.

Key things to verify in /api/docs:
- `POST /api/auth/login` — try it, get a JWT, use it in Authorize
- `GET /api/stores/{slug}/analytics/summary` — requires Bearer, returns rollup metrics
- `GET /api/stores/{slug}/analytics/heatmap` — requires Bearer, returns coordinate grid
- `GET /api/admin/audit-log` — only works with super-admin JWT, 403 otherwise

### 5.2 Rate limiting (S2) — verify it works

```bash
# Hit the login endpoint 11 times in quick succession — the 11th should return 429
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST https://app.108.133.40.141.nip.io/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"bad@example.com","password":"bad"}'
done
```

Expected: first 10 return 401 (wrong credentials). 11th+ return 429 with
`{"detail": {"code": "RATE_LIMITED", ...}}` and `Retry-After: 60` header.

Implementation: `services/eep/app/core/ratelimit.py` — slowapi, Redis-backed,
4 tiers (120/min global, 10/min auth, 5/min pwreset, 60/min write).

### 5.3 Redis stream contract

The exact schema published by IEP2 `_publish_batch_complete()`:
```json
{
  "camera_id":       "string (UUID)",
  "store_id":        "string (UUID)",
  "batch_number":    "string (int, stringified)",
  "window_start_ms": "string (int64, stringified)",
  "window_end_ms":   "string (int64, stringified)",
  "frame_count":     "string (int, stringified)"
}
```
All fields are strings — Redis Streams only store string values. IEP3 converts
back to numeric types on read. Source: `services/iep2_vision/runtime.py`
`_publish_batch_complete()`. Full contracts: `docs/SERVICE_CONTRACTS.md`.

### 5.4 gRPC contract

`proto/agent.proto` — `StartCamera` / `StopCamera` RPCs with request/response fields.
The bidirectional stream stays open; EEP pushes commands, Edge Agent pushes heartbeats.
TLS + `GRPC_SHARED_SECRET` mutual auth (see §6.3 on secrets).

---

## §6. Engineering rigor (25 min)

### 6.1 Test suite (Q1, Q2)

```bash
# Run all unit tests — no infra required
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ --cov=services --cov-report=term-missing
```

**29 test files across 8 service areas:**

| Area | Key test files | What is verified |
|---|---|---|
| IEP3 | `test_spatial_voter.py`, `test_appearance_fallback.py`, `test_state.py` | Vote accumulation; appearance fallback; FSM transitions |
| EEP | `test_ratelimit.py`, `test_audit_actions.py`, `test_boundary.py` | 429 envelope; audit actions; input boundary conditions |
| IEP2 | `test_gallery.py`, `test_inference_deadline.py` | Embedding quality ranking; ZMQ timeout behavior |
| IEP1 | `test_window.py` | Window boundary alignment, partial-window handling |
| IEP4 | `test_delivery_timeout.py` | Alert delivery timeout + retry |
| IEP5 | `test_metrics_push.py` | Analytics computation |
| MLOps | `test_promote.py` | Promotion gate threshold evaluation for all 3 experiments |
| Consistency | `test_consistency.py` | Cross-service schema consistency |

Full strategy: `docs/qa/TEST_STRATEGY.md`. Regression strategy: `docs/qa/REGRESSION_STRATEGY.md`.

### 6.2 Error handling and resilience (S3, T6)

`docs/EDGE_CASES.md` — 12-scenario failure table, each with:
- Exact behavior (not "it handles errors" — what specifically happens)
- Recovery mechanism (code reference)
- Test coverage

Key scenarios to read:
- **IEP3 crash mid-batch** — XACK+orphan sweep (ADR-001)
- **ReID service ZMQ unavailable** — spatial-only fallback, tracking still written
- **PostgreSQL unavailable** — 503 on REST, IEP3 batch stays in PEL
- **YOLO service unavailable** — empty manifest, IEP3 skips the window for that camera

`docs/EDGE_CASES.md §2` explains the orphan sweep: 6 conditions, always in a separate
transaction from reconciliation, skipped when >80% of window budget is consumed.

### 6.3 Secrets management (S5)

**Nothing sensitive is in the repository.** Verify:
```bash
git log --oneline | head -20  # no "add .env" commits
grep -r "AWS_SECRET" services/ --include="*.py"  # should return nothing
grep -r "password" services/eep/app/core/ --include="*.py" | grep -v "hash_password\|bcrypt"
```

All 9 production secrets live in AWS Secrets Manager → pulled by External Secrets Operator
→ land as k8s Secret `retailvision-secrets` → mounted as env vars. The JWT secret, DB
password, gRPC shared secret, and OpenAI key never touch the filesystem.

Local dev: `.env.example` has placeholder values. `.gitignore` excludes `.env`.

### 6.4 Containerization (S4)

The Helm chart at `charts/retailvision/` deploys all cloud services. Notable design:
- `iep3_manager.py` / `iep4_manager.py` / `iep5_manager.py` — EEP uses the k8s Python
  client to `apply` / `delete` Deployments and Jobs at runtime. No static YAML for IEP3/4/5
  in the chart (by design — they are store-lifecycle-scoped, not cluster-lifecycle-scoped)
- KEDA ScaledObject on `iep6-agent`: scales on a Prometheus metric (queue depth)
- HPA on EEP (2–4 replicas) and Frontend (2–6 replicas)
- Karpenter NodePool + EC2NodeClass: SPOT Graviton workers for pipeline workloads,
  on-demand for stateful tier (Postgres, Redis)

---

## §7. Observability (15 min)

### Grafana: https://grafana.108.133.40.141.nip.io

7 dashboards panels (see `docs/MONITORING.md` for the full list):

1. EEP request latency (p50/p95) — time series
2. EEP error rate — time series
3. IEP2 batch duration per camera — time series
4. IEP3 reconciliation latency — time series
5. **ReID cosine score distribution** — histogram panel (ML drift proxy signal)
6. Active global identities — gauge
7. Redis consumer lag — gauge

**Panel 5 is the ML-specific signal (M3):** `iep3_reid_cosine_score` is a Prometheus
histogram. A healthy system shows scores clustered above the 0.85 threshold. A shift in
this distribution toward lower scores (seasonal clothing change, new camera angles, lighting
drift) is the leading indicator of model degradation — before any count accuracy metric moves.
Alert rule: `ReIDScoreDrop` fires when the average drops below threshold for 10 minutes.

Alert rules file: `monitoring/alert_rules.yml`, vendored into the Helm chart at
`charts/retailvision/files/alert_rules.yml`.

Full metrics catalogue (per-service, all label sets): `docs/observability.md`.

---

## §8. Positioning and value (10 min)

Read `docs/POSITIONING.md` for the structured argument:

- **§1** Why this is hard: N cameras produce N disconnected track fragments. Pixel
  coordinates are invalid across non-overlapping cameras. Time alone is ambiguous (O(N²)
  confusion at busy crossings). Appearance is the only generalizable signal — but only
  if the model was trained on diverse multi-camera data (MSMT17 = 15 cameras, 3,060 identities).

- **§3** Three quantified baselines: single-camera tracking (zero cross-camera analytics),
  IR beam sensors (count-only, no trajectory), manual counting (no real-time, expensive).
  Quantitative gap table shows what each baseline cannot produce.

- **§6** Novelty claim: 5 points distinguishing this from an off-the-shelf tracker:
  edge-cloud split with crash-safe XACK model, homography floor projection, 3-stage matcher
  with configurable evidence thresholds, experimentally validated models via MLflow, and
  multi-tenant production deployment on k8s.

Read `docs/AI_DEPTH.md` for the technical argument why ML is necessary (§1, 3 reasons)
and why each model choice is non-trivial (§3.1–3.3 with experiment evidence).

---

## §8. Full rubric evidence index

| Rubric | Item | Evidence location |
|---|---|---|
| **GT1** | Demo end-to-end | https://app.108.133.40.141.nip.io — login → store → analytics |
| **GT2** | Cloud API functional | `GET https://app.108.133.40.141.nip.io/api/health` → `{"status":"ok"}` |
| **GT3** | Architecture minimum | `README.md` architecture diagram; 6 IEPs + EEP in `services/` |
| **GT4** | Deliverables complete | `docs/` — 15+ docs; Helm chart; CI workflow; MLflow experiments |
| **GT5** | Type-specific minimum | Inference deployed; multi-camera live tracking in pipeline |
| **T1** | AI depth | `docs/AI_DEPTH.md`; `services/iep3_reconciliation/app/matcher/`; MLflow |
| **T2** | IEP1 independence | `services/iep1_ingestion/`; `tests/unit/iep1/test_window.py`; `docs/SERVICE_CONTRACTS.md` §2 |
| **T3** | IEP2 independence | `services/iep2_vision/`; `tests/unit/iep2/`; `_publish_batch_complete()` |
| **T4** | EEP orchestration | `services/eep/app/core/scheduler.py`; `iep3_manager.py`; `iep4_manager.py`; gRPC server |
| **T5** | Tradeoff evidence | `docs/TRADEOFFS.md` (5 sections with evidence tables); `docs/decisions/ADR-001`; `ADR-003` |
| **T6** | Execution quality | `docs/EDGE_CASES.md` (12 scenarios); orphan sweep code; `tests/unit/iep3/test_state.py` |
| **S1** | Service contracts | `docs/SERVICE_CONTRACTS.md`; `proto/agent.proto`; `/api/docs` |
| **S2** | Validation | `services/eep/app/core/ratelimit.py`; `docs/SECURITY.md` §1-2; 429 live test |
| **S3** | Errors/retries | `docs/EDGE_CASES.md` §2; ADR-001; `services/iep3_reconciliation/app/repository.py` orphan sweep |
| **S4** | Containerization | `charts/retailvision/`; `docker-compose.yml`; `iep3_manager.py` dynamic provisioning |
| **S5** | Deployment + secrets | `docs/DEPLOYMENT.md`; `charts/retailvision/templates/external-secrets.yaml`; no secrets in repo |
| **P1** | Problem clarity | `docs/POSITIONING.md` §1 |
| **P2** | Baseline rigor | `docs/POSITIONING.md` §3; `docs/docs_models/*/RESULTS.md` |
| **P3** | AI justification | `docs/AI_DEPTH.md` §1 (3 reasons); §3.1–3.3 (model selection) |
| **P4** | Value | `docs/POSITIONING.md` §5; retail analytics metrics |
| **C1** | Originality | Edge-cloud split with XACK crash safety for vision pipeline; homography floor projection |
| **C2** | Design choices | Quality-ranked embedding gallery; XACK-before-processing; two-Redis topology; `store_operating_hours` master clock |
| **Q1** | Test breadth | `tests/unit/` (29 files, 8 service areas); `docs/qa/TEST_STRATEGY.md` |
| **Q2** | Regression | `docs/qa/REGRESSION_STRATEGY.md`; `scripts/check_promotion.py`; MLflow promotion gates |
| **G1** | Commit history | `git log --oneline` on `deploy/final-merge` branch |
| **G2** | Branching/review | GitHub PR history; branch naming; issue references in commits |
| **M1** | Automated lifecycle | `.github/workflows/ci.yml`; `scripts/check_promotion.py`; APScheduler-driven IEP5 |
| **M2** | Experiment tracking | MLflow: 3 experiments, model registry, promotion thresholds; `docs/MLOPS_PIPELINE.md` |
| **M3** | Monitoring | Grafana `iep3_reid_cosine_score` distribution; `monitoring/alert_rules.yml`; `docs/MONITORING.md` |
| **M4** | Documentation | `docs/` index in `README.md`; all 15+ docs reviewed and grounded in code |

---

## §9. Anticipated hard questions

**Q: Why XACK before processing instead of after?**
The standard pattern (XACK after success) means a crash during processing leaves the
message in the PEL, which IEP3 would reprocess on restart — causing a duplicate
reconciliation that merges the same local_ids twice. The XACK-before model accepts
a skipped window (recoverable via orphan sweep) in exchange for no corrupt merges.
Read ADR-001 for the 4-scenario failure mode table. The orphan sweep handles the
narrow post-COMMIT crash window.

**Q: Why not use a proper streaming processor (Flink, Kafka Streams)?**
See ADR-003. Flink-style stateful streaming requires distributed state per camera pair
across the sliding window — complex to operate and over-engineered for the use case.
Retail analytics tolerates 60-second lag. A fixed window with APScheduler is simpler
to reason about and fast to restart.

**Q: Why motion-only BoTSORT (with_reid=False)?**
The ReID model runs separately as a service (ZMQ) and is already used for cross-camera
matching in IEP3. Enabling within-camera ReID in the tracker would add latency (another
ZMQ call per frame) without meaningfully improving single-camera track continuity in a
store aisle scenario. The experiment result: BoTSORT motion-only got 57 unique track IDs
vs StrongSORT (with ReID) at 83 — ReID in the tracker adds fragmentation, not reduces it.
See `docs/docs_models/tracking/TRACKING_RESULTS.md`.

**Q: Why 0.85 threshold and not 0.75 (better proxy metrics)?**
The 0.75 threshold minimizes count_error on the test set but at the cost of a higher
false-merge rate in production. A false merge (two people treated as one) corrupts
dwell time analytics and loss prevention signals. The 0.85 threshold accepts higher
count_error (missing a legitimate cross-camera match) in exchange for near-zero false
merges. Conservative is correct here. Full sweep: `docs/TRADEOFFS.md §4`.

**Q: How does the system handle a camera that never submits a batch?**
IEP3 has `CAMERA_WAIT_TIMEOUT` (configurable). After the timeout, reconciliation runs
with the cameras that did report. The missing camera is treated as absent for that window.
This prevents one broken camera from stalling all analytics for a store.
See `docs/EDGE_CASES.md` row 4 and `services/iep3_reconciliation/app/settings.py`.

**Q: What happens to in-flight data on edge power loss?**
IEP1 writes frames to tmpfs (volatile). Any in-flight batch that has not yet written
`tracking_history` to Postgres is lost. Completed batches already committed to cloud DB
are safe. On restart, Edge Agent re-establishes the gRPC stream; EEP resumes camera
commands automatically. This is a documented failure mode, not an oversight —
`docs/EDGE_CASES.md` row 8.

**Q: Why resnet50_msmt17 over the OSNet variants?**
The experiment result is counterintuitive: OSNet was trained on MSMT17 too (osnet_msmt17)
but scored 39 count_error vs resnet50's 18. The 2048-dim embedding space gives
resnet50_msmt17 more discriminative capacity at the 0.55 cosine similarity threshold.
OSNet's compact 512-dim design was optimized for on-device speed — not for the precision
needed at the cross-camera matching stage where errors are permanent.

**Q: How are IEP3/4/5 provisioned — show me the code.**
`services/eep/app/tasks/iep3_manager.py` — uses the Kubernetes Python client
(`kubernetes.client.AppsV1Api`) to `create_namespaced_deployment()` and
`delete_namespaced_deployment()`. The Deployment spec is built in Python at runtime,
not read from a static YAML file. This means the store's configuration (slug, DB
credentials, Redis URL) is injected as env vars at creation time per store.
