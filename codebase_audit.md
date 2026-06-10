# RetailVision — Codebase Audit
**Date:** 2026-06-10
**Branch:** main
**Status:** Post-stabilisation. All known bugs fixed. Dev stack fully operational on Windows x86/Intel CPU.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Inventory](#2-service-inventory)
3. [Data Flow](#3-data-flow)
4. [Proto / gRPC Contracts](#4-proto--grpc-contracts)
5. [Database Schema](#5-database-schema)
6. [S3 / MinIO Object Storage](#6-s3--minio-object-storage)
7. [Redis Stream Topology](#7-redis-stream-topology)
8. [Named Volumes](#8-named-volumes)
9. [Environment Variables](#9-environment-variables)
10. [Dev vs Production Differences](#10-dev-vs-production-differences)
11. [Key Invariants](#11-key-invariants)
12. [Testing Infrastructure](#12-testing-infrastructure)
13. [Known Bugs and Fixes](#13-known-bugs-and-fixes)
14. [Open Questions / TODOs](#14-open-questions--todos)

---

## 1. System Overview

RetailVision is a multi-camera retail analytics platform. It tracks customers
across camera views in real time, produces canonical per-person trajectories,
measures zone occupancy and dwell time, and exposes analytics to store managers.

**Deployment topology:**

```
CLOUD (Docker Compose / Kubernetes)
  React Frontend           :3000
  EEP (FastAPI + gRPC)     :8000 (REST) / :50051 (gRPC)
  IEP3 Reconciliation      (daemon — no exposed port)
  IEP4 Alerts Daemon       (daemon — Prometheus :8004)
  IEP5 Analytics Job       (one-shot k8s Job — no port)
  IEP6 AI Agent            :8006 (FastAPI REST)
  Live Bridge              :8010 (WebSocket)
  PostgreSQL 16            :5432
  PgBouncer                :5433 (host) → :5432 (internal)
  Redis 7.2                :6379
  MinIO                    :9000 (S3 API) / :9001 (console)
  Prometheus               :9090
  Grafana                  :3001

EDGE (Jetson Orin — k3s / Docker Compose in dev)
  Edge Agent               (systemd on host / compose in dev)
  IEP1 Ingestion Daemon    (k3s pod / compose in dev)
  IEP2 Vision Daemon       (k3s Deployment per camera)
  YOLO Service             :50052 (gRPC health) / ZMQ IPC
  ReID Service             :50053 (gRPC health) / ZMQ IPC
```

---

## 2. Service Inventory

### 2.1 EEP — Control Plane

| Property | Value |
|---|---|
| Role | Cloud control plane: REST API, gRPC command stream to Edge Agent, store config, user management, orchestration |
| Framework | FastAPI 0.115.0 + uvicorn 0.30.1 |
| gRPC | grpcio 1.64.0, serves `AgentService.Connect` bidirectional stream on :50051 |
| Database | SQLAlchemy 2.0.30 + asyncpg 0.29.0 → PgBouncer → PostgreSQL 16 |
| Migrations | Alembic 1.13.1 via psycopg2-binary (direct to postgres:5432, bypasses PgBouncer) |
| Auth | JWT (python-jose 3.3.0 + bcrypt 3.2.2); gRPC auth via `x-agent-token` header |
| S3 | boto3 → MinIO |
| Redis | redis[asyncio] (`REDIS_URL`) |
| Scheduler | APScheduler — fires `evaluate_store_hours()` every `WINDOW_SECONDS` (default 60 s) |
| Ports | `8000` (REST), `50051` (gRPC) |
| Build context | `services/eep/` |
| Key files | `app/main.py`, `app/grpc_server/server.py`, `app/api/routers/`, `app/core/orchestrator.py`, `app/core/shift_closer.py` |

**REST API prefix:** `/api`

**Router groups (16 routers):**

| Router | Module | Purpose |
|---|---|---|
| `auth` | `auth.py` | JWT login/refresh, registration, invite, password reset |
| `stores` | `stores.py` | Create/manage stores |
| `config` | `config.py` | Read-only store config view |
| `draft` | `draft.py` | Versioned floor-plan editor: zones, cameras, calibration, TPS, draft→publish |
| `members` | `members.py` | Org members, roles, invite, remove |
| `employees` | `employees.py` | Staff records, linking to global_ids via punch-in |
| `shifts` | `shifts.py` | Shift patterns and assignments |
| `operating_hours` | `operating_hours.py` | Store open/close schedule (replaces per-camera `camera_schedules`) |
| `punch` | `punch.py` | Employee punch-in/out events and resolver |
| `live` | `live.py` | Reconciled people counts, KPIs, camera health, edge-agent health |
| `alerts` | `alerts.py` | Active alerts, alert history, resolution, alert-rule CRUD |
| `analytics` | `analytics.py` | Read-only rollup endpoints (store, zone, employee, flow, heatmap) |
| `audit` | `audit.py` | Append-only audit log of privileged actions |
| `settings` | `settings.py` | Store/org settings |
| `debug` | `debug.py` | Dev-only — `DEBUG_MODE` gated |
| `dev_pipeline` | `dev_pipeline.py` | Dev-only — `DEBUG_MODE` gated |

**Orchestration:**
APScheduler fires every `WINDOW_SECONDS`. Each tick: (1) loads `store_operating_hours`,
(2) resolves current store-local time per `stores.timezone`, (3) starts/stops cameras
via gRPC `StartCamera`/`StopCamera` to Edge Agent, (4) activates pending config versions,
(5) triggers `shift_closer.close_shift_and_run_iep5()` when a store transitions to
0 running cameras.

---

### 2.2 IEP1 — Ingestion

| Property | Value |
|---|---|
| Role | RTSP capture daemon; writes JPEG frames to tmpfs; publishes window manifests to edge-local Redis |
| Framework | asyncio daemon (`daemon.py`) |
| gRPC | Serves `Iep1Control` (AddCamera, RemoveCamera, GetStatus) + `grpc.health.v1` on two unix sockets |
| Redis | redis[asyncio] — `stream:iep1:{camera_id}` XADD with `maxlen=1000, approximate=True` |
| Frame storage | `{TMPFS_FRAME_ROOT}/{camera_id}/{timestamp_ms}.jpg` (default: `/dev/shm/frames`) |
| Ports | None exposed. Unix sockets only: `iep1_control.sock`, `iep1_health.sock` |
| Build context | `services/iep1_ingestion/` |
| Key files | `app/daemon.py`, `app/worker.py`, `app/window.py` |

**Camera worker architecture:**
Each `CameraWorker` has two concurrent components:
- A dedicated **OS thread** running the blocking `cv2.VideoCapture` loop (stride-paced to `target_fps`).
- An **asyncio task** accumulating frames into 60 s windows and publishing the manifest.

Communication: bounded `asyncio.Queue(maxsize=FRAME_QUEUE_SIZE, default=30)`.
The OS thread delivers frames via `loop.call_soon_threadsafe(_enqueue)` — direct
`put_nowait` from a non-event-loop thread is not safe (see Invariant 7).
If the queue is full, frames are dropped (`IEP1_FRAMES_DROPPED` counter incremented).

**Manifest format** (JSON in Redis field `"manifest"`):
```json
{
  "window_start_ms": 1700000000000,
  "window_end_ms":   1700000060000,
  "batch_number":    0,
  "status":          "online",
  "frames":          [[1700000001234, "/dev/shm/frames/cam-uuid/1700000001234.jpg"]],
  "gaps":            [],
  "frame_count":     28,
  "expected_frames": 30
}
```
`status`: `"online"` (≥80% frames), `"degraded"`, `"offline"` (≤20% frames).

**Metrics:** Prometheus on `IEP1_METRICS_PORT` (default `:9200`)

---

### 2.3 IEP2 — Vision

| Property | Value |
|---|---|
| Role | Per-camera vision pipeline: reads IEP1 manifests → YOLO detect → BoTSORT track → resnet50_msmt17 ReID → tracking_history → batch_complete |
| Framework | asyncio daemon (`runtime.py`) |
| Database | asyncpg → PgBouncer → PostgreSQL 16 |
| Redis | redis[asyncio] — local Redis (XREADGROUP from `stream:iep1:{camera_id}`); server Redis (XADD `stream:iep2:batch_complete`, `stream:iep2:live:{camera_id}`) |
| ZMQ | pyzmq — PUSH to YOLO/ReID, PULL from per-camera result sockets |
| Identity | `LocalIdentityManager` — BoTSORT track IDs → persistent local UUIDs; counter in local Redis at `iep2:id_counter:{camera_id}` |
| Projector | `FloorProjector` — homography, PnP, or TPS from `calibrations` table → floor (x,y) |
| Ports | None (daemon) |
| Build context | `services/iep2_vision/` |
| Key files | `runtime.py`, `detector/detector.py`, `reid/reid.py`, `tracker/tracker.py`, `identity/manager.py`, `persistence/postgres.py`, `ingest/redis_source.py` |

**Startup phases:**
- **Phase A** — drain un-ACKed messages from the consumer group's PEL (crash recovery).
- **Phase B** — normal XREADGROUP blocking reads.

**Processing order per manifest:**
1. For each frame: JPEG from tmpfs → YOLO detect (ZMQ) → BoTSORT update (motion-only, `with_reid=False`) → resnet50_msmt17 ReID embed (ZMQ, 2048-dim) → `LocalIdentityManager` assigns `local_id`
2. Homography projection (`FloorProjector`) — `NULL` if uncalibrated
3. Zone assignment (Shapely hit-test) — `NULL` if uncalibrated
4. Batch commit: `tracking_history` INSERT → `local_centroids` UPSERT → `batch_complete` XADD → XACK → tmpfs frame cleanup

**Key env vars:**

| Var | Default | Description |
|---|---|---|
| `CAMERA_ID` | required | Physical camera UUID |
| `STORE_ID` | required | |
| `WINDOW_SECONDS` | 60 | Must match IEP1 and IEP3 |
| `LOCAL_REDIS_URL` | `redis://localhost:6379/0` | IEP1 manifest stream |
| `SERVER_REDIS_URL` | required | batch_complete stream target |
| `DATABASE_URL_SERVER` | required | plain `postgresql://` |
| `YOLO_INPUT_SOCK` | `ipc:///tmp/sockets/yolo_input.sock` | |
| `REID_INPUT_SOCK` | `ipc:///tmp/sockets/reid_input.sock` | |

**Metrics:** Prometheus on `IEP2_METRICS_PORT` (default `:9201`)

---

### 2.4 IEP3 — Reconciliation

| Property | Value |
|---|---|
| Role | Cloud daemon: reads batch_complete → 3-stage cross-camera identity matching → global identities |
| Framework | asyncio daemon |
| Database | asyncpg → PgBouncer → PostgreSQL 16 |
| Redis | redis[asyncio] — XREADGROUP on `stream:iep2:batch_complete`; consumer group `iep3-{store_id}` |
| XACK policy | XACK-before-processing (see ADR-001) — PEL is always empty after clean run |
| Ports | None |
| Build context | `services/iep3_reconciliation/` |
| Key files | `app/reconciler.py`, `app/matcher/`, `app/state.py`, `app/repository.py`, `app/settings.py` |

**Reconciliation algorithm (3 stages):**

1. **BatchReader** — load `local_centroids` (packed 2048-dim embeddings) for all `local_id`s in this window.
2. **SpatialVoter** — for each pair `(local_id_A from cam_A, local_id_B from cam_B)`: counts windows where both are co-visible within `vote_distance_threshold_m` (default 1.0 m) and `temporal_tolerance_ms` (default 150 ms). A match is confirmed when `votes ≥ min_votes` (default 10) and `vote_rate ≥ min_vote_rate` (default 0.60).
3. **ReidMatcher (appearance fallback)** — fires only when spatial vote rate is ambiguous (winner margin < `ambiguity_margin`, default 0.15). Computes median cosine similarity on packed 2048-dim embeddings; pair confirmed if ≥ `reid_fallback_threshold` (default 0.55).

Unmatched `local_id`s get a new `global_id`. Each completed window runs as a single asyncpg transaction.

**State machine transitions:**

| Transition | Condition |
|---|---|
| NEW → ACTIVE | `global_id` created by matcher for unmatched `local_id` |
| ACTIVE → LOST | No active `global_local_mapping` seen since `window_start_ms`; `lost_since_ts = window_end_ms` |
| LOST → ACTIVE | Match found in a later window; `global_id` reused, `lost_since_ts` cleared |
| LOST → EXITED | `(window_end_ms − lost_since_ts) > grace_seconds × 1000` (default 300 s); a `global_id` just marked LOST this batch never exits in the same batch |
| EXITED | Terminal — mappings deactivated, `local_centroids` deleted |

**Key settings:**

| Var | Default | Description |
|---|---|---|
| `STORE_ID` | required | |
| `WINDOW_SECONDS` | required | must match IEP1/IEP2 |
| `DATABASE_URL_SERVER` | required | plain `postgresql://` |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | |
| `VOTE_DISTANCE_THRESHOLD_M` | `1.0` | max floor distance (m) for a spatial vote |
| `MIN_VOTE_RATE` | `0.6` | min votes/co-visible windows to confirm |
| `MIN_VOTES` | `10` | min raw vote count |
| `TEMPORAL_TOLERANCE_MS` | `150` | max timestamp gap for co-visibility |
| `AMBIGUITY_MARGIN` | `0.15` | vote-rate gap below which appearance fires |
| `REID_FALLBACK_THRESHOLD` | `0.55` | median cosine to confirm appearance match |
| `GRACE_SECONDS` | `300.0` | LOST → EXITED grace period |
| `EMBEDDING_DIM` | `2048` | must match ReID service |
| `COORDINATOR_TIMEOUT_S` | `120.0` | partial-batch timeout |
| `POSITION_WEIGHT_AREA` | `0.7` | canonical position: bbox area weight |
| `POSITION_WEIGHT_CONF` | `0.3` | canonical position: confidence weight |

---

### 2.5 IEP4 — Alerts Daemon

| Property | Value |
|---|---|
| Role | Long-running asyncio daemon (one per store); evaluates alert rules against live tracking state; writes alert events to PostgreSQL |
| Framework | asyncio daemon — no HTTP port |
| Database | asyncpg → PostgreSQL 16 |
| Provisioning | EEP creates a k8s StatefulSet `iep4-<short_id>` when a store version is activated |
| Metrics | Prometheus on `IEP4_METRICS_PORT` (default `:8004`) |
| Build context | `services/iep4_alerts/` |
| Key files | `app/daemon.py`, `app/alerts/`, `app/state/`, `app/persistence/postgres.py` |

---

### 2.6 IEP5 — Analytics Job

| Property | Value |
|---|---|
| Role | End-of-shift analytics aggregation; runs once per shift close and exits |
| Type | One-shot job — not a daemon; exits with code 0 on success, non-zero on error |
| Database | asyncpg → PostgreSQL 16 |
| Metrics | Pushes to Prometheus Pushgateway at job end (no scrape port) |
| Provisioning | EEP creates a k8s `batch/v1` Job via `iep5_manager.run_iep5_job()` at shift close |
| Build context | `services/iep5_analytics/` |
| Key files | `app/main.py`, `app/pipeline.py`, `app/aggregators/`, `app/persistence/postgres.py` |

---

### 2.7 IEP6 — AI Agent

| Property | Value |
|---|---|
| Role | Natural-language Q&A and daily insight reports over store analytics data |
| Framework | FastAPI |
| Scheduler | APScheduler — daily insight report generation (`INSIGHTS_CRON_HOUR`, default 06:00 UTC) |
| Database | PostgreSQL (via `app/core/config.py` settings) |
| Ports | `8006` |
| Build context | `services/iep6_agent/` |
| Key files | `app/main.py`, `app/scheduler.py`, `app/api/routers/agent.py`, `app/agent/` |

---

### 2.8 YOLO Service

| Property | Value |
|---|---|
| Role | Person detection; batches JPEG frames from all IEP2 instances into one inference call |
| Transport | ZMQ PULL (bind `yolo_input.sock`) → ZMQ PUSH (connect `yolo_output_{camera_id}.sock`) |
| Protocol | msgpack serialisation |
| Prod backend | RT-DETR-x TRT FP16 engine (Jetson ARM64) — `service.py` |
| Dev backend | RT-DETR-x `.pt` default; YOLO11n `.pt` as low-compute fallback — `service_dev.py` |
| Class filter | Class 0 (person) only; classes 1–79 filtered |
| Health | gRPC health on `unix:///tmp/sockets/yolo_health.sock` + TCP `:50052`; NOT_SERVING → SERVING after model load |
| Device toggle | Redis key `inference:device`; capability announced to `inference:capability:detector` |
| Ports | `50052` (gRPC health) |
| Build context | `services/yolo_service/` |

**Batch settings:**

| Setting | Dev | Prod |
|---|---|---|
| `YOLO_MAX_BATCH_SIZE` | 4 | 32 |
| `YOLO_BATCH_TIMEOUT_MS` | 500 | 20 |

**Request/response:**
```python
# Request (msgpack)
{"request_id": str, "camera_id": str, "timestamp_ms": int, "frame": bytes}

# Response (msgpack)
{"request_id": str, "detections": [{"label": "person", "confidence": float, "bbox_xyxy": [x1,y1,x2,y2]}]}
```

---

### 2.9 ReID Service

| Property | Value |
|---|---|
| Role | Person re-identification; extracts 2048-dim L2-normalised embeddings from person crops |
| Model | resnet50_msmt17 (prod: `service.py`; dev: `service_dev.py` via boxmot ReidAutoBackend) |
| Transport | ZMQ PULL (bind `reid_input.sock`) → ZMQ PUSH (connect `reid_output_{camera_id}.sock`) |
| Protocol | msgpack serialisation |
| Embedding | 2048-dim float32 L2-normalised → 8192 bytes packed per embedding |
| Preprocessing | 128×256 crop, ImageNet normalisation, CHW float32 |
| Health | gRPC health on `unix:///tmp/sockets/reid_health.sock` + TCP `:50053` |
| Device toggle | Redis key `inference:device`; capability announced to `inference:capability:reid` |
| Ports | `50053` (gRPC health) |
| Build context | `services/reid_service/` |
| Metrics | Prometheus `:9401`, job "reid" |

**Request/response:**
```python
# Request (msgpack)
{"request_id": str, "camera_id": str, "track_id": int, "timestamp_ms": int, "crop": bytes}

# Response (msgpack)
{"request_id": str, "embedding": bytes}  # 2048 × float32 = 8192 bytes, L2-normalised
```

---

### 2.10 Edge Agent

| Property | Value |
|---|---|
| Role | Translates EEP gRPC StartCamera/StopCamera commands into k3s Deployment operations and IEP1 AddCamera/RemoveCamera calls |
| Runtime | asyncio daemon; systemd service on Jetson host; `edge_agent_dev` compose service in dev |
| EEP connection | gRPC bidirectional stream; reconnects with exponential backoff (1 s → 60 s, 30% jitter) |
| Backends | k3s (primary) via `kubernetes` client; Docker fallback |
| IEP1 control | gRPC via `unix:///dev/shm/sockets/iep1_control.sock` (prod) |
| Health sockets | YOLO: `{YOLO_HEALTH_TCP_ADDR}:50052`; ReID: `{REID_HEALTH_TCP_ADDR}:50053`; IEP1: unix socket |
| Outgoing queue | maxsize=200 |
| Auth | `x-agent-token: {AGENT_SECRET}` on all EEP gRPC calls |
| Build context | `services/edge_agent/` |
| Key files | `app/agent.py`, `app/k8s_manager.py` |

**Startup sequence (enforced order):**
1. Init backend (k3s or Docker)
2. `_wait_for_health("yolo")` — gRPC health poll until SERVING
3. `_wait_for_health("reid")` — gRPC health poll until SERVING
4. `_wait_for_health("iep1")` — gRPC health poll until SERVING
5. `_restore_active_cameras()` — reads k3s ConfigMaps, re-adds to IEP1
6. `_connect_to_eep()` — opens bidirectional stream; first message must be `Heartbeat`

**StartCamera per camera:** ConfigMap + Deployment applied → wait IEP2 SERVING → `AddCamera` IEP1

**StopCamera per camera:** cancel health watcher → `RemoveCamera` IEP1 → delete Deployment + ConfigMap

---

### 2.11 Live Bridge

| Property | Value |
|---|---|
| Role | Real-time WebSocket relay: streams per-frame detections and frames to the frontend |
| Framework | FastAPI + uvicorn + websockets |
| Redis | redis[asyncio] — XREADGROUP on `stream:iep2:live:{camera_id}` (consumer group per client) |
| S3 | boto3 — generates presigned frame URLs (30 s TTL) when `S3_LIVE_MODE=s3` |
| Transport modes | `embed` (frame_b64 in WS message, dev) vs `s3` (presigned URL, prod) |
| Ports | `8010` |
| Build context | `services/live_bridge/` |

---

### 2.12 Infrastructure Services

| Service | Image | Host Port | Role |
|---|---|---|---|
| PostgreSQL | `postgres:16-alpine` | `5432` | Primary database |
| PgBouncer | `edoburu/pgbouncer:1.22.1-p0` | `5433` | Connection pool (session mode) |
| Redis | `redis:7.2.4-alpine` | `6379` | Stream bus + local identity counter |
| MinIO | `minio/minio:RELEASE.2024-11-07T00-52-20Z` | `9000` / `9001` | S3-compatible object storage |
| Prometheus | `prom/prometheus:v2.51.0` | `9090` | Metrics aggregation |
| Grafana | `grafana/grafana:10.4.1` | `3001` | Dashboards |
| Frontend | `./frontend` (React 18) | `3000` | Web UI |

---

## 3. Data Flow

### 3.1 Full Pipeline Flow

```
Camera (RTSP)
    │
    ▼ cv2.VideoCapture (OS thread)
IEP1 CameraWorker
    │ write JPEG → {TMPFS_FRAME_ROOT}/{cam}/{ts_ms}.jpg
    │ XADD stream:iep1:{camera_id}  {manifest: json}
    │
    ▼ XREADGROUP iep2-{camera_id}  (Phase A: drain PEL; Phase B: normal reads)
IEP2 Vision Daemon (one Deployment per camera)
    │
    ├─ ZMQ PUSH ──► YOLO Service ──► ZMQ PUSH yolo_output_{camera_id}
    │                   bbox_xyxy[], confidence, class=person
    │
    ├─ BoTSORT tracking (motion-only, with_reid=False)
    │   track_id (int) → local_id (UUID, Redis counter iep2:id_counter:{cam})
    │
    ├─ ZMQ PUSH ──► ReID Service ──► ZMQ PUSH reid_output_{camera_id}
    │                   embedding: 2048×float32 L2-norm (8192 bytes)
    │
    ├─ FloorProjector (homography/PnP/TPS) → floor_x, floor_y
    ├─ PostgreSQL INSERT tracking_history ON CONFLICT DO NOTHING
    ├─ PostgreSQL UPSERT local_centroids (packed 2048-dim embeddings)
    ├─ XADD stream:iep2:batch_complete
    ├─ XACK stream:iep1:{camera_id}
    └─ DELETE tmpfs frame files
    │
    ▼ XREADGROUP iep3-{store_id}  (XACK-before-processing — see ADR-001)
IEP3 Reconciliation (asyncpg transaction per window)
    │
    ├─ BatchCoordinator waits for all cameras (timeout: COORDINATOR_TIMEOUT_S)
    ├─ SpatialVoter — co-visible pairs within vote_distance_threshold_m + temporal_tolerance_ms
    ├─ Vote confirmation (min_votes + min_vote_rate)
    ├─ ReidMatcher fallback — fires when ambiguity_margin triggered (cosine ≥ reid_fallback_threshold)
    ├─ PositionSelector — canonical floor position per global_id
    ├─ StateManager — ACTIVE/LOST/EXITED transitions
    ├─ INSERT global_tracking_history
    ├─ UPSERT global_identities, global_local_mapping, global_embeddings
    └─ periodic orphan_sweep
    │
    ├──► IEP4 Alerts Daemon (asyncio daemon, one per store)
    │       evaluates rules → writes alert events
    │
    └──► IEP5 Analytics Job (one-shot k8s Job at shift close, triggered by EEP shift_closer)
             aggregates visits, dwell, zone flows → analytics tables
             │
             └──► IEP6 AI Agent (FastAPI :8006)
                      NL Q&A + daily insight reports over analytics tables
```

### 3.2 Store Configuration Flow (UI-driven)

```
User (Browser)
    │ HTTP REST → EEP /api
    ├─ POST /stores → creates store row
    ├─ POST .../versions/draft → creates draft config version
    ├─ POST .../floor-plan/upload → stores image in S3
    ├─ PUT .../floor-plan/scale → sets pixels_per_metre
    ├─ POST .../zones → creates zone polygons
    ├─ POST /store/{slug}/cameras → creates physical_cameras row
    ├─ POST .../camera-configs → places camera on floor plan
    ├─ POST .../camera-configs/{id}/calibration/homography
    │   ─ computes 3×3 homography matrix from ≥4 point pairs
    │   ─ stores in calibrations table
    ├─ POST .../calibration/verify → sets calibration.status = 'verified'
    └─ POST .../versions/draft/activate → promotes draft → active
                                          → EEP provisions IEP4 StatefulSet
```

### 3.3 Edge Agent Command Flow

```
EEP scheduler tick → gRPC ControlMessage.start_camera
    ▼
Edge Agent _handle_start_camera
    │ Apply k3s ConfigMap + Deployment → IEP2 pod starts
    │ Wait IEP2 gRPC health = SERVING
    │ IEP1.AddCamera(camera_id, rtsp_url, target_fps, window_seconds)
    ▼
IEP1 / IEP2 operational
```

---

## 4. Proto / gRPC Contracts

### 4.1 `proto/agent.proto`

Service: `AgentService.Connect` (bidirectional streaming)

**Upstream (edge → cloud):** `AgentMessage`
- `Heartbeat { store_id, agent_version, timestamp_ms }`
- `CameraStatusReport { camera_id, container_status, timestamp_ms }`

**Downstream (cloud → edge):** `ControlMessage`
- `StartCamera { camera_id, store_id, rtsp_url, target_fps, window_seconds, camera_config_id }`
- `StopCamera { camera_id, store_id }`

Auth: `x-agent-token` metadata header. First message from edge **must** be a `Heartbeat`; EEP aborts with `INVALID_ARGUMENT` otherwise.

### 4.2 `proto/iep1_control.proto`

Service: `Iep1Control` (unary RPCs, unix socket only)

| RPC | Request | Response |
|---|---|---|
| `AddCamera` | `CameraConfig { camera_id, rtsp_url, target_fps, window_seconds, store_id }` | `AddCameraResponse { success, error }` |
| `RemoveCamera` | `RemoveCameraRequest { camera_id }` | `RemoveCameraResponse { success }` |
| `GetStatus` | `Empty` | `Iep1StatusResponse { cameras: [CameraStatus] }` |

`CameraStatus.status`: `"capturing"` | `"reconnecting"` | `"stopped"`

### 4.3 Generated Stub Locations

| Service | Stub directory |
|---|---|
| EEP | `services/eep/app/grpc_generated/` |
| Edge Agent | `services/edge_agent/app/grpc_generated/` |
| IEP1 (server) | `services/iep1_ingestion/app/grpc_generated/` |

Regenerate: `bash scripts/generate_protos.sh` (requires `grpcio-tools==1.64.0`).

---

## 5. Database Schema

All tables in the `public` schema of the `retailvision` database.
Migrations: `services/eep/alembic/versions/` (0001–0020).

### 5.1 User / Store / Membership

| Table | Key columns | Notes |
|---|---|---|
| `users` | `id UUID PK`, `email`, `hashed_password`, `full_name`, `is_owner` | Owner = can create stores |
| `stores` | `id UUID PK`, `name`, `slug UNIQUE`, `address`, `timezone` | slug is URL identifier |
| `store_members` | `id UUID PK`, `store_id→stores`, `user_id→users`, `role` | role: owner/manager/viewer |
| `store_member_permissions` | `member_id→store_members`, `permission` | Fine-grained permissions |
| `invitations` | `id UUID PK`, `store_id→stores`, `email`, `token`, `expires_at` | Pending invitations |
| `refresh_tokens` | `token_hash`, `user_id→users`, `expires_at` | JWT refresh |
| `audit_logs` | `id UUID PK`, `store_id`, `user_id`, `action`, `entity_type`, `entity_id`, `payload JSONB` | All write operations |

### 5.2 Store Configuration

| Table | Key columns | Notes |
|---|---|---|
| `store_config_versions` | `id UUID PK`, `store_id→stores`, `status` (draft/active/archived), `activate_at` | One active per store |
| `sections` | `id UUID PK`, `version_id→store_config_versions`, `name`, `position_x/y` | Sub-areas of store |
| `floor_plans` | `id UUID PK`, `section_id→sections`, `original_s3_key`, `display_s3_key`, `pixels_per_metre FLOAT`, `image_width/height INT` | |
| `zones` | `id UUID PK`, `section_id→sections`, `name`, `polygon GEOGRAPHY(POLYGON)` | PostGIS polygon |
| `obstacles` | `id UUID PK`, `section_id→sections`, `polygon GEOGRAPHY(POLYGON)` | Dead zones |
| `coordinate_frames` | `id UUID PK`, `section_id→sections` | World coordinate anchor |
| `store_settings` | `store_id→stores`, `activation_countdown_sec`, `chunk_duration_sec` | |
| `store_operating_hours` | `store_id→stores`, `day_of_week`, `open_time`, `close_time`, `is_closed` | Replaces `camera_schedules` (migration 0016) |
| `version_sync_events` | `id UUID PK`, `store_id→stores`, `version_id`, `status` | Async activation tracking |

### 5.3 Camera Configuration

| Table | Key columns | Notes |
|---|---|---|
| `physical_cameras` | `id UUID PK`, `store_id→stores`, `name`, `rtsp_url`, `is_active`, `stream_width/height` | Hardware device |
| `camera_configs` | `id UUID PK`, `version_id→store_config_versions`, `physical_camera_id→physical_cameras`, `section_id→sections`, `floor_x/y FLOAT`, `frame_s3_key` | Camera placement |
| `camera_zone_coverage` | `camera_config_id→camera_configs`, `zone_id→zones` | Which zones a camera covers |
| `calibrations` | `id UUID PK`, `camera_config_id→camera_configs`, `method` (homography/pnp/tps), `status` (pending/ok/verified/rejected/failed), `is_current BOOL`, `homography_matrix JSONB`, `rms_reprojection_error FLOAT` | Partial unique index: one `is_current=true` per config |
| `camera_runtime_sessions` | `camera_id TEXT`, `store_id UUID`, `started_at`, `ended_at` | Runtime session log |

### 5.4 Tracking / Analytics

| Table | Key columns | Notes |
|---|---|---|
| `tracking_history` | `id BIGSERIAL PK`, `store_id UUID`, `camera_id TEXT` (not FK), `local_id UUID`, `timestamp_ms BIGINT`, `floor_x/y DOUBLE`, `zone_id UUID`, `bbox_confidence FLOAT4`, `bbox_area FLOAT4` | `UNIQUE(camera_id, local_id, timestamp_ms)` — ON CONFLICT DO NOTHING |
| `local_centroids` | `camera_id TEXT`, `local_id UUID`, `centroid BYTEA` (2048×float32 = **8192 bytes**, L2-norm), `updated_at` | EMA of resnet50_msmt17 embeddings |
| `global_identities` | `id UUID PK`, `store_id UUID→stores`, `global_id UUID`, `state` (ACTIVE/LOST/EXITED), `is_employee BOOL`, `first_seen_ms`, `last_seen_ms`, `lost_since_ts` | One row per unique person |
| `global_local_mapping` | `global_id UUID`, `camera_id TEXT`, `local_id UUID`, `is_active BOOL` | Cross-camera identity link |
| `global_embeddings` | `global_id UUID`, `camera_id TEXT`, `embedding BYTEA` | Per-camera centroid (EMA α=0.3) |
| `global_tracking_history` | `id BIGSERIAL PK`, `global_id UUID`, `store_id UUID`, `batch_number INT`, `timestamp_ms BIGINT`, `floor_x/y DOUBLE`, `zone_id UUID`, `source_camera TEXT`, `selection_score FLOAT4` | IEP3 output |

### 5.5 Workforce / Scheduling

| Table | Notes |
|---|---|
| `employees` | Employee records linked to store |
| `employee_embeddings` | ReID embeddings for employee linking |
| `employee_sections` | Employee ↔ section assignments |
| `shift_patterns` | Recurring shift templates |
| `shift_instances` | Concrete shift occurrences |

### 5.6 Alembic Migrations

Location: `services/eep/alembic/versions/`

| Migration | Description |
|---|---|
| `0001_indexes.py` | Performance indexes on tracking_history, global_tracking_history |
| `0002_constraints.py` | FK and unique constraints (idempotent) |
| `0003_pgbouncer_compat.py` | Removes prepared-statement usage incompatible with PgBouncer |
| `0004_batch_number_bigint.py` | batch_number → BIGINT |
| `0005_embedding_dim_2048.py` | Widens centroid BYTEA constraints from 2048 bytes (OSNet 512-dim) to 8192 bytes (resnet50_msmt17 2048-dim) |
| `0006_camera_intrinsics_pnp.py` | PnP calibration support |
| `0007_tracking_bbox_pixels.py` | Add pixel bbox columns to tracking_history |
| `0008_tps_method.py` | TPS calibration method |
| `0009_remove_sections.py` | Schema simplification |
| `0010_analytics_foundation.py` | Analytics rollup tables |
| `0011_alert_rules.py` | Alert rule CRUD tables |
| `0012_crs_stop_reason_eep_restart.py` | Camera runtime session stop reason |
| `0013_embedding_store.py` | global_embeddings schema |
| `0014_employee_linking.py` | Employee ↔ global_id linking tables |
| `0015_drop_audit_action_check.py` | |
| `0016_store_operating_hours.py` | `store_operating_hours` master clock, replaces `camera_schedules` |
| `0017_alert_severity.py` | Alert severity column |
| `0018_drop_alert_configs.py` | Retire legacy `alert_configs` table |
| `0019_recon_trace.py` | Reconciliation trace tables for VD diagnostics |
| `0020_agent_tables.py` | IEP6 agent conversation / insight tables |

Alembic connects directly to `postgres:5432` via psycopg2 (bypasses PgBouncer — required because Alembic uses prepared statements).

---

## 6. S3 / MinIO Object Storage

Bucket: `retailvision` (default, configurable via `S3_BUCKET`)

| Object type | Key pattern |
|---|---|
| Floor plan original | `floor-plans/{store_id}/{section_id}/original.{ext}` |
| Floor plan display (resized) | `floor-plans/{store_id}/{section_id}/display.{ext}` |
| Camera calibration frame | `calibration-frames/{store_id}/{config_id}/frame.{ext}` |
| Calibration intrinsic XML | `calibration-files/{store_id}/{config_id}/intrinsic.xml` |
| Calibration extrinsic XML | `calibration-files/{store_id}/{config_id}/extrinsic.xml` |
| Live frames (S3 mode) | `live-frames/{store_id}/{camera_id}/{timestamp_ms}.jpg` |

Presigned URL expiry: 30 s (Live Bridge), longer TTL (EEP config page).
`S3_PUBLIC_URL` is used for browser-visible presigned URL generation. Dev: `http://localhost:9000`.

---

## 7. Redis Stream Topology

Two Redis instances: **edge-local Redis** (streams from IEP1→IEP2) and **server Redis** (streams from IEP2→IEP3, Live Bridge). In dev both map to the same Redis instance.

| Stream | Redis | Producer | Consumer | Maxlen | Notes |
|---|---|---|---|---|---|
| `stream:iep1:{camera_id}` | Edge-local | IEP1 | IEP2 (`XREADGROUP iep2-{camera_id}`) | 1000 (≈) | Window manifest JSON |
| `stream:iep2:batch_complete` | Server | IEP2 | IEP3 (`XREADGROUP iep3-{store_id}`) | 500 (≈) | Batch metadata for reconciliation |
| `stream:iep2:live:{camera_id}` | Server | IEP2 `LivePublisher` | Live Bridge | 500 (≈) | Per-frame detections (optional) |

**XACK ordering (IEP2):** tracking_history → local_centroids → batch_complete XADD → **XACK** → tmpfs cleanup.

**IEP3 XACK timing:** ACKs immediately on receipt, before reconciliation (ADR-001). Crash recovery via `orphan_sweep`.

**Local identity counter:** `iep2:id_counter:{camera_id}` (Redis integer) — persists across IEP2 restarts.

---

## 8. Named Volumes

All volumes in Docker Compose project `retail-edge`:

| Volume name | Type | Contents | Shared by |
|---|---|---|---|
| `ipc-sockets` | tmpfs (RAM) | YOLO/ReID ZMQ IPC sockets | yolo-service, reid-service, iep2_vision |
| `iep1-sockets` | tmpfs (RAM) | IEP1 gRPC control/health unix sockets | iep1-daemon, edge_agent_dev |
| `frame-store` | tmpfs (RAM) | JPEG frames (short-lived) | iep1-daemon, iep2_vision |
| `postgres_data` | bind (disk) | PostgreSQL data directory | postgres |
| `redis_data` | bind (disk) | Redis persistence (AOF/RDB) | redis |
| `minio_data` | bind (disk) | MinIO object store | minio |
| `grafana_data` | bind (disk) | Grafana dashboards | grafana |

**Jetson production:** tmpfs volumes become host paths (`/dev/shm/sockets`). IPC sockets visible to IEP2 pods via k3s hostPath volume mount.

---

## 9. Environment Variables

### 9.1 Shared config (injected via `x-shared-config` anchor)

Applied to: `eep`, `iep2_vision`, `iep3_reconciliation`

| Variable | Dev default | Notes |
|---|---|---|
| `WINDOW_SECONDS` | `60` | **Must be identical across IEP1, IEP2, IEP3** |
| `DATABASE_URL_SERVER` | `postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision` | asyncpg plain dialect |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | batch_complete stream + server-side pub/sub |

### 9.2 EEP-specific

| Variable | Dev default | Notes |
|---|---|---|
| `DATABASE_URL_EEP` | `postgresql+asyncpg://…@pgbouncer:5432/retailvision` | SQLAlchemy async dialect |
| `ALEMBIC_DATABASE_URL` | `postgresql+psycopg2://…@postgres:5432/retailvision` | Direct — bypasses PgBouncer |
| `REDIS_URL` | `redis://redis:6379/0` | EEP pub/sub |
| `JWT_SECRET` | `dev-secret-change-in-production` | JWT signing |
| `AGENT_SECRET` | `dev-agent-secret` | gRPC auth; empty = no auth |
| `DEBUG_MODE` | `false` (`true` in dev) | Enables debug endpoints |
| `ML_SERVICES_TIMEOUT_S` | `120` (`300` in dev) | YOLO/ReID startup wait |
| `S3_ACCESS_KEY` | `retailvision` | |
| `S3_SECRET_KEY` | `retailvision_dev` | |
| `S3_BUCKET` | `retailvision` | |
| `S3_ENDPOINT_URL` | `http://minio:9000` | |
| `S3_PUBLIC_URL` | `http://localhost:9000` | Browser-visible URL |

### 9.3 IEP1-specific

| Variable | Dev default | Notes |
|---|---|---|
| `LOCAL_REDIS_URL` | `redis://redis:6379/0` | |
| `IEP1_CONTROL_SOCK` | `unix:///tmp/iep1-sockets/iep1_control.sock` | |
| `IEP1_HEALTH_SOCK` | `unix:///tmp/iep1-sockets/iep1_health.sock` | |
| `TMPFS_FRAME_ROOT` | `/dev/shm/frames` | |
| `JPEG_QUALITY` | `85` | |

### 9.4 PgBouncer notes

`pool_mode = session` (required by asyncpg). `default_pool_size = 50`. `server_reset_query = DISCARD ALL`. Config: `infra/pgbouncer/pgbouncer.ini`.

---

## 10. Dev vs Production Differences

| Aspect | Development (Windows x86 / Intel CPU) | Production (Jetson Orin ARM64) |
|---|---|---|
| Compose override | `-f docker-compose.yml -f docker-compose.dev.yml` | `-f docker-compose.yml` |
| YOLO backend | RT-DETR-x `.pt` (YOLO11n as low-compute fallback) — `service_dev.py` | RT-DETR-x TRT FP16 engine — `service.py` |
| ReID backend | boxmot ReidAutoBackend (PyTorch) on CPU — `service_dev.py` | TRT resnet50_msmt17 engine — `service.py` |
| YOLO batch | 4 frames, 500 ms timeout | 32 frames, 20 ms timeout |
| ReID batch | 8 crops, 200 ms timeout | 64 crops, 50 ms timeout |
| Model load time | 30–60 s | 5–10 min first boot (TRT compile) |
| IEP2 orchestration | `docker compose --profile dev up iep2_vision` (one instance) | k3s Deployment per camera, managed by Edge Agent |
| Edge Agent | `edge_agent_dev` compose service (`--profile edge`) | systemd service on Jetson host |
| IPC socket path | Docker volume → `/tmp/sockets` inside container | hostPath `/dev/shm/sockets` |
| IEP1 socket path | Docker volume → `/tmp/iep1-sockets` | hostPath `/dev/shm/sockets` |
| `DEBUG_MODE` | `true` | `false` |
| `ML_SERVICES_TIMEOUT_S` | `300` | `120` |
| RTSP sources | File paths via `cv2.VideoCapture` | Real RTSP streams |
| `LOCAL_REDIS_URL` | Same Redis instance as server | Separate edge-device Redis |
| TLS (EEP gRPC) | Disabled (insecure channel) | TLS with CA cert |
| k3s | Not used | Required |

---

## 11. Key Invariants

1. **`WINDOW_SECONDS` must be identical across IEP1, IEP2, and IEP3.** Mismatch causes silent reconciliation failure. Source of truth: `x-shared-config` anchor in `docker-compose.yml`.

2. **PgBouncer must be in session mode.** asyncpg uses the extended query protocol (PARSE → BIND → EXECUTE). Transaction mode splits sub-messages across connections → "prepared statement does not exist". Config: `pool_mode = session` in `infra/pgbouncer/pgbouncer.ini`.

3. **`ALEMBIC_DATABASE_URL` must point directly to `postgres:5432`, not PgBouncer.** Alembic uses psycopg2 prepared statements internally.

4. **`tracking_history` uses `camera_id TEXT` (not a FK).** Physical camera UUIDs stored as text. Unique constraint: `(camera_id, local_id, timestamp_ms)` with `ON CONFLICT DO NOTHING` for idempotent replay.

5. **ReID embeddings are always 2048-dim float32 L2-normalised = 8192 bytes.** `EMBEDDING_DIM=2048` must match between ReID service, IEP2 (`ReidClient`), IEP3 (`EMBEDDING_DIM` setting), and the `calibrations` table. L2 norm ≈ 1.0 ± 1e-5. This changed from OSNet 512-dim in migration 0005.

6. **IEP2 XACK fires AFTER `batch_complete` is published but BEFORE tmpfs cleanup.** Order: tracking_history → local_centroids → batch_complete XADD → XACK → `_cleanup_frames`.

7. **`loop.call_soon_threadsafe(_enqueue)` in IEP1 capture thread.** The asyncio Queue must be accessed from the event loop thread only. Direct `put_nowait` from the capture thread is not thread-safe (was BUG-010).

8. **Calibration must be verified before tracking data is meaningful.** If a camera config lacks a verified calibration, `FloorProjector` returns `None`; `floor_x/floor_y` will be NULL in tracking_history and IEP3 cannot do spatial voting for that camera.

9. **`camera_id` in `tracking_history` is the physical camera UUID (TEXT), not `camera_config_id`.** IEP3 joins on this to find `camera_configs` and load homography.

10. **IEP2 module entry point must use `python -m services.iep2_vision.main`.** The `-m` flag adds WORKDIR to `sys.path` for relative imports to resolve (was BUG-011).

11. **IEP3 spatial matching requires co-visibility history.** `min_votes=10` means at least 10 windows where two `local_id`s were both observed are needed before the matcher will confirm a cross-camera link. New cameras or cameras with sparse traffic will have a cold-start period where all unmatched `local_id`s get new `global_id`s.

---

## 12. Testing Infrastructure

### 12.1 Documentation

| File | Scope |
|---|---|
| `docs/qa/TEST_STRATEGY.md` | Full test strategy (unit, integration, E2E, accuracy) |
| `docs/qa/REGRESSION_STRATEGY.md` | Regression test approach |
| `docs/decisions/ADR-001-xack-before-processing.md` | IEP3 XACK timing decision |
| `docs/decisions/ADR-002-two-redis-topology.md` | Edge vs server Redis split |
| `docs/decisions/ADR-003-windowed-batch-60s.md` | 60 s window choice |
| `docs/decisions/ADR-004-edge-vs-cloud-split.md` | Edge/cloud boundary decision |
| `docs/operations/iep3-orphan-runbook.md` | Detecting and remediating orphaned global identities |

### 12.2 Automated Tests

| Path | Type | Requires |
|---|---|---|
| `tests/unit/iep3/` | Unit | No external services — gate, matcher, selector, state |
| `tests/unit/iep1/` | Unit | No external services |
| `tests/unit/iep2/` | Unit | No external services |
| `tests/unit/iep4/` | Unit | No external services |
| `tests/unit/iep5/` | Unit | No external services |
| `tests/unit/eep/` | Unit | No external services |
| `tests/unit/consistency/` | Unit | No external services |
| `tests/unit/mlops/` | Unit | No external services |
| `tests/e2e/test_iep3_reconciler.py` | Integration | PostgreSQL only — 3-camera reconciliation scenario |
| `tests/e2e/test_full_pipeline.py` | Integration | Full stack (EEP DEBUG_MODE, IEP1/IEP2 images) |
| `tests/e2e/test_cloud.py` | Integration | Cloud services |

### 12.3 Utility Scripts

| Script | Purpose |
|---|---|
| `scripts/generate_protos.sh` | Regenerate gRPC stubs; applies import path fixes |
| `scripts/check_env_example.py` | Verify `.env.example` covers all required `Field(...)` vars |
| `scripts/gen_dev_certs.sh` | Generate self-signed CA + EEP cert for dev TLS |
| `scripts/export_yolo_trt.py` | Export YOLOv8 to TensorRT FP16 (Jetson) |
| `scripts/export_reid_trt.py` | Export resnet50_msmt17 to TensorRT FP16 (Jetson) |
| `scripts/bootstrap-edge-k3s.sh` | Bootstrap Jetson with k3s and RetailVision stack |
| `scripts/check_promotion.py` | Pre-promotion checks |
| `scripts/ci_verify.py` | CI verification script |

---

## 13. Known Bugs and Fixes

| ID | Title | Status |
|---|---|---|
| BUG-001 | PgBouncer image not found on Docker Hub | Fixed |
| BUG-002 | YOLO/ReID not buildable on x86/Intel | Fixed — CPU dev variants (`service_dev.py`) created |
| BUG-003 | grpcio 1.64.0 requires protobuf≥5.26.1; all services pinned to 4.25.3 | Fixed — upgraded to 5.27.2 |
| BUG-004 | `.env` REPLACE_ME placeholders override compose defaults → auth failure | Fixed |
| BUG-005 | EEP crash: `No module named 'alembic.config'` — migrations dir shadowed pip package | Fixed — migrations moved to `alembic/versions/` |
| BUG-006 | IEP3 crash: `No module named 'pydantic'` — missing from requirements.txt | Fixed |
| BUG-007 | Alembic migration 0002 fails: `ADD CONSTRAINT IF NOT EXISTS` invalid SQL on PG16 | Fixed — `DO $$ … EXCEPTION WHEN duplicate_object` |
| BUG-008 | asyncpg + PgBouncer transaction mode → "prepared statement does not exist" | Fixed — session mode |
| BUG-009 | All uvicorn logs silenced after Alembic: `fileConfig` disables existing loggers | Fixed — `disable_existing_loggers=False` |
| BUG-010 | IEP1 capture thread dies after 1 frame: `run_coroutine_threadsafe(queue.put_nowait(...))` raises TypeError | Fixed — `loop.call_soon_threadsafe(_enqueue)` |
| BUG-011 | IEP2 `ModuleNotFoundError: No module named 'services'` — CMD ran script directly | Fixed — CMD changed to `python -m services.iep2_vision.main` |
| BUG-012 | IEP2 `ModuleNotFoundError: No module named 'boto3'` — boto3 imported at module level in `redis_source.py` | Fixed — lazy import inside `make_s3_client()` |

---

## 14. Open Questions / TODOs

- **IEP3 cold start:** New cameras require `min_votes=10` co-visible windows (≈10 minutes at default 60 s windows) before spatial matching confirms any cross-camera links. During this period all `local_id`s get unique `global_id`s. Not a bug, but a known accuracy gap at store open.

- **Live Bridge stream:** `stream:iep2:live:{camera_id}` is only populated when `IEP2.live_stream_enabled=True`. Verify this defaults to `True` in production or is set via env var in the k3s ConfigMap.

- **mTLS:** Dev uses insecure gRPC. Production migration path documented in `docs/security/mtls-migration.md` — not yet implemented in compose or k3s manifests.

- **Grafana dashboards:** Prometheus scrape targets and Grafana provisioning config not confirmed populated. Both services start but dashboard content depends on provisioning files in `infra/`.

- **Employee ReID linking:** `employee_embeddings` table and `is_employee` flag in `global_identities` exist (migration 0014). The punch-in flow creates the link via `employees` router. Confirm IEP3 uses this to suppress employee `global_id`s from customer counts.

- **Video sync across cameras:** For spatial voting to be accurate, camera clocks must agree within `temporal_tolerance_ms` (150 ms default). No NTP enforcement is documented for the edge device.

- **`GRACE_SECONDS` tuning:** Default 300 s. High-dwell stores (supermarkets) may need higher values to avoid splitting one visit into two `global_id`s when a person stands still for >5 minutes outside a camera's view.
