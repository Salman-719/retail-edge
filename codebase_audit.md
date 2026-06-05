# RetailVision — Codebase Audit
**Date:** 2026-06-05  
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
  OSNet ReID Service       :50053 (gRPC health) / ZMQ IPC
```

---

## 2. Service Inventory

### 2.1 EEP — Edge Entry Point

| Property | Value |
|---|---|
| Role | Cloud control plane: REST API, gRPC command stream to Edge Agent, store config, user management |
| Framework | FastAPI 0.115.0 + uvicorn 0.30.1 |
| gRPC | grpcio 1.64.0, serves `AgentService.Connect` bidirectional stream |
| Database | SQLAlchemy 2.0.30 + asyncpg 0.29.0 → PgBouncer → PostgreSQL 16 |
| Migrations | Alembic 1.13.1 via psycopg2-binary (direct to postgres:5432, bypasses PgBouncer) |
| Auth | JWT (python-jose 3.3.0 + bcrypt 3.2.2); gRPC auth via `x-agent-token` header |
| S3 | boto3 1.34.69 → MinIO |
| Redis | redis[asyncio] 5.0.4 (`REDIS_URL`) |
| Ports | `8000` (REST), `50051` (gRPC) |
| Build context | `services/eep/` |
| Module path | `/app/` (WORKDIR inside container) |
| Key files | `app/main.py`, `app/grpc_server/server.py`, `app/grpc_server/interceptor.py`, `app/api/routers/` |

**REST API prefix:** `/api`

**Router groups:**
- `/api/auth/` — register, login, refresh, logout, forgot-password, reset-password
- `/api/stores`, `/api/store/{slug}/` — store CRUD
- `/api/store/{slug}/members/` — invite, manage members
- `/api/store/{slug}/versions/`, `/api/store/{slug}/versions/draft/` — config versioning
- `/api/store/{slug}/draft/sections/{section_id}/` — floor plans, zones, obstacles
- `/api/store/{slug}/cameras`, `/api/store/{slug}/draft/sections/{section_id}/camera-configs` — camera registration and placement
- `/api/store/{slug}/draft/camera-configs/{config_id}/calibration/` — homography, file upload, verify
- `/api/store/{slug}/employees/`, `/api/store/{slug}/shifts/` — workforce management
- `/api/store/{slug}/audit/`, `/api/store/{slug}/settings/`, `/api/store/{slug}/schedules/`

**gRPC `AgentService.Connect`:**  
Bidirectional streaming RPC. Edge Agent dials out, holds the stream open, and
receives `ControlMessage` (StartCamera/StopCamera commands). Sends `AgentMessage`
(Heartbeat, CameraStatusReport) upstream. Auth: `x-agent-token` header must
match `AGENT_SECRET` env var (intercepted by `AgentAuthInterceptor`); health
checks also require the token when `AGENT_SECRET` is non-empty.

---

### 2.2 IEP1 — Ingestion Edge Processor 1

| Property | Value |
|---|---|
| Role | RTSP capture daemon; writes JPEG frames to tmpfs; publishes manifests to local Redis |
| Framework | asyncio daemon |
| gRPC | Serves `Iep1Control` on unix socket only (no TCP) |
| Redis | redis 5.0.3 (async); `stream:iep1:{camera_id}` XADD with `maxlen=1000, approximate=True` |
| Frame storage | `/dev/shm/frames/{camera_id}/{timestamp_ms}.jpg` (tmpfs) |
| ZMQ | None — publishes to Redis, not ZMQ |
| Ports | None exposed. Unix sockets only: `iep1_control.sock`, `iep1_health.sock` |
| Build context | `services/iep1_ingestion/` |
| Module path | `services.iep1_ingestion.app.*` (WORKDIR `/workspace`) |
| Key files | `app/daemon.py`, `app/worker.py`, `app/window.py` |

**Camera lifecycle:**
- `AddCamera(CameraConfig)` → spawns `CameraWorker` (one per camera)
- Worker has two components: a blocking capture thread (`cv2.VideoCapture`) and an async window loop
- Capture thread uses `loop.call_soon_threadsafe(_enqueue)` to safely deliver frames to asyncio queue
- Window loop accumulates frames into `WindowAccumulator`, publishes `WindowManifest` every `window_seconds`
- `RemoveCamera` stops the worker and cleans `/dev/shm/frames/{camera_id}/`

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

---

### 2.3 IEP2 — Ingestion Edge Processor 2 (Vision Pipeline)

| Property | Value |
|---|---|
| Role | Vision pipeline daemon: reads IEP1 manifests → YOLO → OSNet → ByteTrack → tracking_history → batch_complete |
| Framework | asyncio daemon (`runtime.py`) + FastAPI debug UI (`app/main.py` via `iep2_dev` compose profile) |
| Database | asyncpg 0.29.0 → PgBouncer → PostgreSQL 16 |
| Redis | redis 5.0.3 — local Redis for XREADGROUP consumer; server Redis for batch_complete publish |
| ZMQ | pyzmq 25.1.2 — PUSH to YOLO/OSNet, PULL from per-camera result sockets |
| Identity | `LocalIdentityManager` — ByteTrack track IDs → persistent local UUIDs; counter in local Redis at `iep2:id_counter:{camera_id}` |
| Projector | `FloorProjector` — homography matrix from `calibrations` table → floor (x,y) |
| Ports | None (daemon). `iep2_dev` FastAPI profile: `8002` |
| Build context | `services/iep2_vision/` |
| Module path | `services.iep2_vision.*` (WORKDIR `/workspace`, CMD `python -m services.iep2_vision.main`) |
| Key files | `runtime.py`, `detector/detector.py`, `reid/reid.py`, `tracker/tracker.py`, `identity/manager.py`, `persistence/postgres.py`, `ingest/redis_source.py` |

**Daemon mode settings** (pydantic `BaseSettings`, read from env vars):

| Env var | Default | Description |
|---|---|---|
| `CAMERA_ID` | — | Required. Physical camera UUID |
| `CAMERA_CONFIG_ID` | — | Optional. UUID for homography load |
| `STORE_ID` | — | Required |
| `WINDOW_SECONDS` | 60 | Must match IEP1 and IEP3 |
| `LOCAL_REDIS_URL` | `redis://localhost:6379/0` | IEP1 manifest stream |
| `SERVER_REDIS_URL` | — | batch_complete stream target |
| `DATABASE_URL_SERVER` | — | asyncpg URL (plain `postgresql://`) |
| `YOLO_INPUT_SOCK` | `ipc:///tmp/sockets/yolo_input.sock` | |
| `OSNET_INPUT_SOCK` | `ipc:///tmp/sockets/osnet_input.sock` | |
| `HEALTH_SOCK` | `unix:///tmp/sockets/iep2_health_{camera_id}.sock` | Per-camera gRPC health |

**Processing order per manifest:**
1. For each frame path: read JPEG from tmpfs → YOLO detect → OSNet embed → ByteTrack update
2. Write `tracking_history` rows (all frames in manifest)
3. Update `local_centroids` (EMA of embeddings per local_id)
4. Publish to `stream:iep2:batch_complete` (maxlen=500, approximate=True)
5. XACK the IEP1 manifest message
6. Delete tmpfs frame files (`_cleanup_frames`)

**batch_complete message fields:**
```json
{
  "store_id": "...", "camera_id": "...", "camera_config_id": "...",
  "batch_number": 0, "window_start_ms": ..., "window_end_ms": ...,
  "frame_count": 28, "track_count": 3
}
```

---

### 2.4 IEP3 — Reconciliation

| Property | Value |
|---|---|
| Role | Cloud daemon: reads batch_complete → cross-camera ReID → global identities |
| Framework | asyncio daemon |
| Database | asyncpg 0.29.0 → PgBouncer → PostgreSQL 16 |
| Redis | redis[asyncio] 5.0.4 — XREADGROUP on `stream:iep2:batch_complete` |
| ReID threshold | `REID_THRESHOLD=0.75` (cosine similarity) |
| Coord system | Floor (x,y) from `global_tracking_history`; requires calibration |
| Ports | None |
| Build context | `services/iep3_reconciliation/` |
| Module path | `services.iep3_reconciliation.app.*` |
| Key files | `app/reconciler.py`, `app/settings.py` |

**Reconciliation pipeline:**
1. `RedisStreamConsumer` XREADGROUP from `stream:iep2:batch_complete`; XACK on receipt (before processing — see ADR-001)
2. Load `tracking_history` for the batch window → build observation set per camera
3. `cross_camera_gate` — spatial-temporal plausibility filter; rejects cross-camera matches that violate speed limit (`MAX_SPEED_MPS=1.5`)
4. `ReidMatcher` — cosine similarity on `local_centroids` embeddings → attempt to link to existing `global_identity`
5. `PositionSelector` — score per observation (bbox confidence × area weighting); select one floor position per global_id per batch
6. Write `global_tracking_history` + update `global_identities` and `global_local_mapping`
7. `orphan_sweep` — periodic cleanup of global_ids not seen for `GRACE_SECONDS=300`

**Key environment variables:**

| Var | Default | Description |
|---|---|---|
| `STORE_ID` | required | |
| `WINDOW_SECONDS` | 60 | Must match IEP1 and IEP2 |
| `DATABASE_URL_SERVER` | required | `postgresql://` (plain asyncpg) |
| `SERVER_REDIS_URL` | required | |
| `COORDINATOR_TIMEOUT_S` | 120 | |
| `REID_THRESHOLD` | 0.75 | Cosine similarity cutoff |
| `MAX_SPEED_MPS` | 1.5 | Cross-camera gate speed limit |
| `EMBEDDING_DIM` | 512 | Must match OSNet output |
| `CENTROID_EMA_ALPHA` | 0.3 | Exponential moving average for centroid updates |
| `POSITION_WEIGHT_AREA` | 0.7 | Scoring weight for bbox area |
| `POSITION_WEIGHT_CONF` | 0.3 | Scoring weight for detection confidence |
| `GRACE_SECONDS` | 300.0 | Orphan TTL before exit |

---

### 2.5 YOLO Service

| Property | Value |
|---|---|
| Role | Person detection; batches JPEG frames from all IEP2 instances into one inference call |
| Transport | ZMQ PULL (bind `yolo_input.sock`) → ZMQ PUSH (connect `yolo_output_{camera_id}.sock`) |
| Protocol | msgpack serialisation |
| Prod backend | TensorRT (Jetson ARM64, JetPack base image) |
| Dev backend | ultralytics 8.1.34, YOLOv8n `.pt`, CPU |
| Health | gRPC health on `unix:///tmp/sockets/yolo_health.sock` + TCP `:50052`; NOT_SERVING → SERVING after model load |
| Ports | `50052` (host → TCP gRPC health) |
| Build context | `services/yolo_service/` (prod), repo root (dev — needs `yolov8n.pt`) |

**Request format:**
```python
msgpack.packb({
    "request_id":   str,   # UUID
    "camera_id":    str,
    "timestamp_ms": int,
    "frame":        bytes, # JPEG
})
```

**Response format:**
```python
{
    "request_id": str,
    "detections": [
        {"label": "person", "confidence": float, "bbox_xyxy": [x1,y1,x2,y2]},
        ...
    ]
}
```
Only class 0 (person) detections returned. Classes 1–79 filtered out.

**Dev batch settings:** `YOLO_MAX_BATCH_SIZE=4`, `YOLO_BATCH_TIMEOUT_MS=500`  
**Prod batch settings:** `YOLO_MAX_BATCH_SIZE=32`, `YOLO_BATCH_TIMEOUT_MS=20`

---

### 2.6 OSNet ReID Service

| Property | Value |
|---|---|
| Role | Person re-identification; extracts 512-dim L2-normalised embeddings from person crops |
| Transport | ZMQ PULL (bind `osnet_input.sock`) → ZMQ PUSH (connect `osnet_output_{camera_id}.sock`) |
| Protocol | msgpack serialisation |
| Prod backend | TRT OSNet x1.0 (Jetson ARM64), `EMBEDDING_DIM=512` |
| Dev backend | torchvision ResNet-18 + avgpool + L2-norm, CPU, `EMBEDDING_DIM=512` |
| Health | gRPC health on `unix:///tmp/sockets/osnet_health.sock` + TCP `:50053` |
| Ports | `50053` (host → TCP gRPC health) |
| Build context | `services/osnet_service/` |

**Request format:**
```python
msgpack.packb({
    "request_id":   str,
    "camera_id":    str,
    "track_id":     int,
    "timestamp_ms": int,
    "crop":         bytes,  # JPEG person crop
})
```

**Response format:**
```python
{
    "request_id": str,
    "embedding":  bytes,  # 512 × float32 = 2048 bytes, L2-normalised
}
```

**Dev batch settings:** `OSNET_MAX_BATCH_SIZE=8`, `OSNET_BATCH_TIMEOUT_MS=200`  
**Prod batch settings:** `OSNET_MAX_BATCH_SIZE=64`, `OSNET_BATCH_TIMEOUT_MS=50`

---

### 2.7 Edge Agent

| Property | Value |
|---|---|
| Role | Thin gRPC relay: translates StartCamera/StopCamera commands from EEP into k3s Deployment operations |
| Runtime | asyncio daemon; systemd service on Jetson host; `edge_agent_dev` compose service (dev) |
| EEP connection | gRPC bidirectional stream; reconnects with exponential backoff + 30% jitter |
| k3s API | `kubernetes==29.0.0` — creates/deletes `iep2-{camera_id}` Deployment + `camera-{camera_id}` ConfigMap |
| IEP1 control | gRPC via `unix:///dev/shm/sockets/iep1_control.sock` (prod hostPath) |
| Health sockets | YOLO: `localhost:50052`; OSNet: `localhost:50053`; IEP1: `unix:///dev/shm/sockets/iep1_health.sock` |
| Auth | `x-agent-token: {AGENT_SECRET}` on all EEP gRPC calls |
| Ports | None |
| Build context | `services/edge_agent/` |
| Module path | `services.edge_agent.app.*` (WORKDIR `/workspace`, ENTRYPOINT `python -m services.edge_agent.app.main`) |
| Key files | `app/agent.py`, `app/k8s_manager.py` |

**Startup sequence (enforced):**
1. `km.init_k8s_clients()` — load kubeconfig
2. `_wait_for_health("yolo", YOLO_HEALTH_SOCK)` — gRPC health poll
3. `_wait_for_health("osnet", OSNET_HEALTH_SOCK)` — gRPC health poll
4. `_wait_for_health("iep1", IEP1_HEALTH_SOCK)` — gRPC health poll
5. `_restore_active_cameras()` — reads k3s Deployments, re-adds to IEP1
6. `_connect_to_eep()` — opens bidirectional stream

**StartCamera ordering (per camera):**
1. Apply k3s ConfigMap + Deployment → IEP2 pod starts
2. `_wait_for_iep2_health(camera_id)` — poll `iep2_health_{cam}.sock`
3. `_add_camera_to_iep1(camera_id, rtsp_url, ...)` — AddCamera RPC

**StopCamera ordering (per camera):**
1. `watcher.cancel()` — cancel IEP2 health watch task
2. `stub.RemoveCamera(camera_id)` — IEP1 gRPC call
3. `km.delete_iep2(camera_id)` — delete k3s Deployment + ConfigMap

**Reconnect backoff:** `sleep = backoff + random.uniform(0, backoff × 0.3)`, doubles each attempt, cap 60s.

---

### 2.8 Live Bridge

| Property | Value |
|---|---|
| Role | Real-time WebSocket relay: streams per-frame detections to frontend |
| Framework | FastAPI 0.111.0 + uvicorn + websockets 12.0 |
| Redis | redis 5.0.8 — subscribes to `stream:iep2:live:{camera_id}` |
| S3 | boto3 1.34.144 — generates presigned frame URLs (30 s TTL) |
| Ports | `8010` |
| Stream | `stream:iep2:live:{camera_id}` (maxlen=500), published by IEP2 `LivePublisher` when `live_stream_enabled=True` |

---

### 2.9 Infrastructure Services

| Service | Image | Host Port | Role |
|---|---|---|---|
| PostgreSQL | `postgres:16-alpine` | `5432` | Primary database |
| PgBouncer | `edoburu/pgbouncer:1.22.1-p0` | `5433` | Connection pool (session mode) |
| Redis | `redis:7.2.4-alpine` | `6379` | Stream bus + local identity counter |
| MinIO | `minio/minio:RELEASE.2024-11-07T00-52-20Z` | `9000` / `9001` | S3-compatible object storage |
| Prometheus | `prom/prometheus:v2.51.0` | `9090` | Metrics |
| Grafana | `grafana/grafana:10.4.1` | `3001` | Dashboards |
| Frontend | `./frontend` (React) | `3000` | Web UI |

---

## 3. Data Flow

### 3.1 Full Pipeline Flow

```
Camera (RTSP)
    │
    ▼ cv2.VideoCapture
IEP1 CameraWorker
    │ write JPEG → /dev/shm/frames/{cam}/{ts_ms}.jpg
    │ XADD stream:iep1:{camera_id}  {manifest: json}
    │
    ▼ XREADGROUP iep2_workers
IEP2 Vision Daemon (one per camera)
    │
    ├─ ZMQ PUSH ──► YOLO Service ──► ZMQ PUSH per-camera results
    │                   bbox_xyxy[], confidence, label=person
    │
    ├─ ZMQ PUSH ──► OSNet Service ──► ZMQ PUSH per-camera results
    │                   embedding: 512×float32 L2-norm
    │
    ├─ ByteTrack (in-memory, persists across batches)
    │   track_id (int) → local_id (UUID, Redis-persisted counter)
    │
    ├─ PostgreSQL INSERT tracking_history ON CONFLICT DO NOTHING
    ├─ PostgreSQL UPSERT local_centroids (EMA update)
    ├─ XADD stream:iep2:batch_complete {batch metadata}
    ├─ XACK stream:iep1:{camera_id}
    └─ DELETE /dev/shm/frames/{cam}/*.jpg
    │
    ▼ XREADGROUP
IEP3 Reconciliation
    │
    ├─ Load tracking_history + local_centroids for batch window
    ├─ cross_camera_gate (speed plausibility)
    ├─ ReidMatcher (cosine similarity on centroids)
    ├─ PositionSelector (score = bbox_conf × area_weight)
    ├─ INSERT global_tracking_history
    ├─ UPSERT global_identities, global_local_mapping
    └─ periodic orphan_sweep
```

### 3.2 Store Configuration Flow (UI-driven)

```
User (Browser)
    │ HTTP REST → EEP /api
    ├─ POST /stores → creates store row
    ├─ POST /store/{slug}/sections → creates section
    ├─ POST /store/{slug}/versions/draft → creates draft config version
    ├─ POST .../floor-plan/upload → stores image in S3, creates floor_plans row
    ├─ PUT .../floor-plan/scale → sets pixels_per_metre
    ├─ POST .../zones → creates zone polygons
    ├─ POST /store/{slug}/cameras → creates physical_cameras row
    ├─ POST .../camera-configs → places camera on floor plan
    ├─ POST .../camera-configs/{id}/frame → stores calibration frame in S3
    ├─ POST .../camera-configs/{id}/calibration/homography
    │   ─ computes 3×3 homography matrix from ≥4 point pairs
    │   ─ stores in calibrations table (rms_reprojection_error, matrix JSON)
    ├─ POST .../calibration/verify → sets calibration.status = 'verified'
    └─ POST .../versions/draft/activate → promotes draft → active
```

### 3.3 Edge Agent Command Flow

```
EEP gRPC stream
    │ ControlMessage.start_camera / stop_camera
    ▼
Edge Agent _handle_start_camera / _handle_stop_camera
    │ k3s apply ConfigMap + Deployment (create IEP2 pod)
    │ wait IEP2 gRPC health = SERVING
    │ IEP1 AddCamera / RemoveCamera
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

Auth: `x-agent-token` metadata header on every RPC call.

### 4.2 `proto/iep1_control.proto`

Service: `Iep1Control` (unary RPCs, unix socket only)

| RPC | Request | Response |
|---|---|---|
| `AddCamera` | `CameraConfig { camera_id, rtsp_url, target_fps, window_seconds, store_id }` | `AddCameraResponse { success, error }` |
| `RemoveCamera` | `RemoveCameraRequest { camera_id }` | `RemoveCameraResponse { success }` |
| `GetStatus` | `Empty` | `Iep1StatusResponse { cameras: [CameraStatus { camera_id, status, last_frame_ts, frames_dropped }] }` |

`CameraStatus.status`: `"capturing"` | `"reconnecting"` | `"stopped"`

### 4.3 Generated Stub Locations

| Service | Stub directory | Import fix applied |
|---|---|---|
| EEP | `services/eep/app/grpc_generated/` | `from app.grpc_generated import agent_pb2` |
| Edge Agent | `services/edge_agent/app/grpc_generated/` | `from app.grpc_generated import {agent,iep1_control}_pb2` |
| IEP1 (server) | `services/iep1_ingestion/app/grpc_generated/` | `from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2` |

Regenerate stubs: `bash scripts/generate_protos.sh` (requires `grpcio-tools==1.64.0` in venv).

---

## 5. Database Schema

All tables in the `public` schema of the `retailvision` database.

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
| `floor_plans` | `id UUID PK`, `section_id→sections`, `original_s3_key`, `display_s3_key`, `pixels_per_metre FLOAT`, `image_width/height INT` | Scale set separately |
| `zones` | `id UUID PK`, `section_id→sections`, `name`, `polygon GEOGRAPHY(POLYGON)` | PostGIS polygon |
| `obstacles` | `id UUID PK`, `section_id→sections`, `polygon GEOGRAPHY(POLYGON)` | Dead zones for tracking |
| `coordinate_frames` | `id UUID PK`, `section_id→sections` | World coordinate system anchor |
| `store_settings` | `store_id→stores`, `activation_countdown_sec`, `chunk_duration_sec` | Operational config |
| `alert_configs` | `store_id→stores`, `zone_capacity_threshold`, `dwell_alert_seconds` | Alert rules |
| `version_sync_events` | `id UUID PK`, `store_id→stores`, `version_id`, `status` | Async activation tracking |

### 5.3 Camera Configuration

| Table | Key columns | Notes |
|---|---|---|
| `physical_cameras` | `id UUID PK`, `store_id→stores`, `name`, `rtsp_url`, `is_active`, `stream_width/height` | Hardware device |
| `camera_configs` | `id UUID PK`, `version_id→store_config_versions`, `physical_camera_id→physical_cameras`, `section_id→sections`, `floor_x/y FLOAT`, `frame_s3_key` | Camera placement |
| `camera_zone_coverage` | `camera_config_id→camera_configs`, `zone_id→zones` | Which zones a camera covers |
| `calibrations` | `id UUID PK`, `camera_config_id→camera_configs`, `method` (homography/calibration_files), `status` (pending/ok/verified/rejected/failed), `is_current BOOL`, `homography_matrix JSONB`, `rms_reprojection_error FLOAT`, `coverage_score FLOAT`, `point_count INT` | Partial unique index: one `is_current=true` per config |
| `camera_runtime_sessions` | `camera_id TEXT`, `store_id UUID`, `started_at`, `ended_at` | Runtime session log |

### 5.4 Tracking / Analytics

| Table | Key columns | Notes |
|---|---|---|
| `tracking_history` | `id BIGSERIAL PK`, `store_id UUID→stores`, `camera_id TEXT` (not FK — physical camera UUID as text), `local_id UUID`, `timestamp_ms BIGINT`, `floor_x/y DOUBLE`, `zone_id UUID`, `bbox_confidence FLOAT4`, `bbox_area FLOAT4` | `UNIQUE(camera_id, local_id, timestamp_ms)` — ON CONFLICT DO NOTHING |
| `local_centroids` | `camera_id TEXT`, `local_id UUID`, `centroid BYTEA` (512×float32, L2-norm), `updated_at` | EMA of OSNet embeddings |
| `global_identities` | `id UUID PK`, `store_id UUID→stores`, `global_id UUID`, `is_employee BOOL`, `first_seen_ms`, `last_seen_ms` | One row per unique person |
| `global_local_mapping` | `global_id UUID`, `camera_id TEXT`, `local_id UUID` | Cross-camera identity link |
| `global_embeddings` | `global_id UUID`, `embedding BYTEA` | Global centroid (reconciled) |
| `global_tracking_history` | `id BIGSERIAL PK`, `global_id UUID`, `store_id UUID`, `version_id UUID`, `batch_number INT`, `timestamp_ms BIGINT`, `floor_x/y DOUBLE`, `zone_id UUID`, `source_camera TEXT`, `source_local_id UUID`, `selection_score FLOAT4` | IEP3 output; floor_x/y require calibration |

### 5.5 Workforce / Scheduling

| Table | Notes |
|---|---|
| `employees` | Employee records linked to store |
| `employee_embeddings` | ReID embeddings for employee exclusion |
| `employee_sections` | Employee ↔ section assignments |
| `sections` | (also used for scheduling context) |
| `shift_patterns` | Recurring shift templates |
| `shift_instances` | Concrete shift occurrences |
| `test_runs`, `test_run_cameras` | Camera test session records |

### 5.6 Alembic Migrations

Location: `services/eep/db_migrations/versions/`

| Migration | Description |
|---|---|
| `0001_indexes.py` | Performance indexes on tracking_history, global_tracking_history |
| `0002_constraints.py` | FK constraints, unique constraints (idempotent `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object ...`) |
| `0003_pgbouncer_compat.py` | Removes prepared-statement usage incompatible with PgBouncer |

Alembic connects directly to `postgres:5432` via psycopg2 (bypasses PgBouncer — required because Alembic uses prepared statements internally).

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
| Live frames (if S3 mode) | `live-frames/{store_id}/{camera_id}/{timestamp_ms}.jpg` |

Presigned URL expiry: 30 seconds (Live Bridge), varies (EEP config page uses longer TTL).

Public vs private: `S3_PUBLIC_URL` is used for presigned URL generation visible to the browser. In dev, `S3_PUBLIC_URL=http://localhost:9000` (direct MinIO access). In production, this would be a CDN endpoint.

---

## 7. Redis Stream Topology

| Stream | Producer | Consumer | Maxlen | Notes |
|---|---|---|---|---|
| `stream:iep1:{camera_id}` | IEP1 (`XADD`) | IEP2 (`XREADGROUP iep2_workers`) | 1000 (≈) | Manifest JSON per window |
| `stream:iep2:batch_complete` | IEP2 (`XADD`) | IEP3 (`XREADGROUP`) | 500 (≈) | Batch metadata for reconciliation |
| `stream:iep2:live:{camera_id}` | IEP2 `LivePublisher` | Live Bridge | 500 (≈) | Per-frame detections (optional) |

Consumer group name: `iep2_workers` (IEP1 → IEP2), IEP3 uses its own group name.

**XACK ordering (IEP2):** tracking_history → local_centroids → batch_complete → **XACK** → tmpfs cleanup.  
If IEP2 crashes after XACK but before cleanup, orphaned tmpfs files remain. IEP1 `RemoveCamera` cleans the whole directory.

**IEP3 XACK timing:** ACKs immediately on receipt, before reconciliation (see `docs/decisions/ADR-001-xack-before-processing.md`). Crash recovery relies on `run_orphan_sweep()`.

**Local identity counter:** `iep2:id_counter:{camera_id}` (Redis string, integer) — persists across IEP2 restarts. Counter is incremented by `LocalIdentityManager` when a new local UUID is minted.

---

## 8. Named Volumes

All volumes in Docker Compose project `retail-edge`:

| Volume name | Full Docker name | Type | Contents | Shared by |
|---|---|---|---|---|
| `ipc-sockets` | `retail-edge_ipc-sockets` | tmpfs (RAM) | YOLO/OSNet ZMQ IPC sockets | yolo-service, osnet-service, iep2_vision, iep2_dev |
| `iep1-sockets` | `retail-edge_iep1-sockets` | tmpfs (RAM) | IEP1 gRPC control/health unix sockets | iep1-daemon, edge_agent_dev |
| `frame-store` | `retail-edge_frame-store` | tmpfs (RAM) | JPEG frames (short-lived) | iep1-daemon, iep2_vision |
| `postgres_data` | `retail-edge_postgres_data` | bind (disk) | PostgreSQL data directory | postgres |
| `redis_data` | `retail-edge_redis_data` | bind (disk) | Redis persistence (AOF/RDB) | redis |
| `minio_data` | `retail-edge_minio_data` | bind (disk) | MinIO object store | minio |
| `grafana_data` | `retail-edge_grafana_data` | bind (disk) | Grafana dashboards | grafana |

**Jetson production:** tmpfs volumes become host paths (`/dev/shm/sockets`). IPC sockets visible to IEP2 pods via k3s hostPath volume mount.

---

## 9. Environment Variables

### 9.1 Shared config (injected via `x-shared-config` anchor)

Applied to: `eep`, `iep2_vision`, `iep3_reconciliation`, `iep2_dev`

| Variable | Dev default | Notes |
|---|---|---|
| `WINDOW_SECONDS` | `60` | **Must be identical across IEP1, IEP2, IEP3.** Mismatch = silent reconciliation failure |
| `DATABASE_URL_SERVER` | `postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision` | asyncpg plain dialect (not SQLAlchemy) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | batch_complete stream + reload signals |

### 9.2 EEP-specific

| Variable | Dev default | Notes |
|---|---|---|
| `DATABASE_URL_EEP` | `postgresql+asyncpg://retailvision:retailvision_dev@pgbouncer:5432/retailvision` | SQLAlchemy async dialect |
| `ALEMBIC_DATABASE_URL` | `postgresql+psycopg2://retailvision:retailvision_dev@postgres:5432/retailvision` | Direct — bypasses PgBouncer |
| `REDIS_URL` | `redis://redis:6379/0` | EEP pub/sub |
| `JWT_SECRET` | `dev-secret-change-in-production` | JWT signing |
| `AGENT_SECRET` | `dev-agent-secret` | gRPC auth; empty = no auth |
| `DEBUG_MODE` | `false` (`true` in dev override) | Enables debug endpoints |
| `ML_SERVICES_TIMEOUT_S` | `120` (`300` in dev — ultralytics load time) | YOLO/OSNet startup wait |
| `S3_ACCESS_KEY` | `retailvision` | |
| `S3_SECRET_KEY` | `retailvision_dev` | |
| `S3_BUCKET` | `retailvision` | |
| `S3_ENDPOINT_URL` | `http://minio:9000` | |
| `S3_PUBLIC_URL` | `http://localhost:9000` | Browser-visible URL |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | smtp.gmail.com / 587 / empty | Email for invitations/reset |

### 9.3 IEP1-specific

| Variable | Dev default | Notes |
|---|---|---|
| `LOCAL_REDIS_URL` | `redis://redis:6379/0` | IEP1 manifest stream |
| `IEP1_CONTROL_SOCK` | `unix:///tmp/iep1-sockets/iep1_control.sock` | |
| `IEP1_HEALTH_SOCK` | `unix:///tmp/iep1-sockets/iep1_health.sock` | |
| `TMPFS_FRAME_ROOT` | `/dev/shm/frames` | |
| `JPEG_QUALITY` | `85` | |

### 9.4 PgBouncer notes

`pool_mode = session` (required by asyncpg). `default_pool_size = 50`. `server_reset_query = DISCARD ALL`. Config at `infra/pgbouncer/pgbouncer.ini`. Credentials at `infra/pgbouncer/userlist.txt` (md5 or plaintext password).

---

## 10. Dev vs Production Differences

| Aspect | Development (Windows x86 / Intel CPU) | Production (Jetson Orin ARM64) |
|---|---|---|
| Compose override | `-f docker-compose.yml -f docker-compose.dev.yml` | `-f docker-compose.yml` |
| YOLO backend | ultralytics YOLOv8n `.pt` on CPU | TensorRT FP16 engine |
| OSNet backend | ResNet-18 + avgpool + L2-norm on CPU | OSNet x1.0 TRT engine |
| YOLO batch | 4 frames, 500 ms timeout | 32 frames, 20 ms timeout |
| OSNet batch | 8 crops, 200 ms timeout | 64 crops, 50 ms timeout |
| Model load time | 30–60 s (ultralytics first load) | 5–10 min first boot (TRT compile) |
| IEP2 orchestration | `docker compose --profile dev up iep2_vision` (one instance) | k3s Deployment per camera, managed by Edge Agent |
| Edge Agent | `edge_agent_dev` compose service (`--profile edge`) | systemd service on Jetson host |
| IPC socket path | Docker volume `retail-edge_ipc-sockets` → `/tmp/sockets` inside container | hostPath `/dev/shm/sockets` |
| IEP1 socket path | Docker volume `retail-edge_iep1-sockets` → `/tmp/iep1-sockets` | hostPath `/dev/shm/sockets` |
| `DEBUG_MODE` | `true` | `false` |
| `ML_SERVICES_TIMEOUT_S` | `300` | `120` |
| RTSP sources | File paths (`/workspace/testing-data/`) via `cv2.VideoCapture` | Real RTSP streams |
| `LOCAL_REDIS_URL` | Same Redis instance as server | Separate edge-device Redis |
| `SERVER_REDIS_URL` | Same Redis instance | Cloud Redis endpoint |
| TLS (EEP gRPC) | Disabled (no cert files, insecure channel) | TLS with CA cert; mTLS roadmap in `docs/security/mtls-migration.md` |
| k3s | Not used | Required |

---

## 11. Key Invariants

These must hold at all times. Violations cause silent data corruption without obvious errors.

1. **`WINDOW_SECONDS` must be identical across IEP1, IEP2, and IEP3.** A mismatch means IEP3 receives batch_complete messages spanning different time intervals than it expects, causing all reconciliation to be incorrect. Source of truth: `x-shared-config` anchor in `docker-compose.yml` (`${WINDOW_SECONDS:-60}`).

2. **PgBouncer must be in session mode.** asyncpg uses the extended query protocol (PARSE → BIND → EXECUTE). Transaction mode reuses server connections between messages, splitting these sub-messages across different connections and causing "prepared statement does not exist" errors. Config: `pool_mode = session` in `infra/pgbouncer/pgbouncer.ini`.

3. **EEP's `ALEMBIC_DATABASE_URL` must point directly to postgres:5432, not PgBouncer.** Alembic uses psycopg2 prepared statements internally. Running migrations through PgBouncer causes failures regardless of pool mode.

4. **`tracking_history` uses `camera_id TEXT` (not a FK).** Physical camera UUIDs are stored as text strings. The unique constraint is `(camera_id, local_id, timestamp_ms)` with `ON CONFLICT DO NOTHING`. This allows idempotent replay of IEP2 output.

5. **OSNet embeddings are always 512-dim float32 L2-normalised.** `EMBEDDING_DIM=512` must match between OSNet service, IEP2 (`OsNetClient`), IEP3 (`EMBEDDING_DIM` setting), and the `calibrations` table computation. L2 norm ≈ 1.0 ± 1e-5.

6. **IEP2 XACK fires AFTER batch_complete is published but BEFORE tmpfs cleanup.** Order: tracking_history → local_centroids → batch_complete XADD → XACK → `_cleanup_frames`. A crash after XACK leaves orphaned tmpfs files; IEP1 `RemoveCamera` cleans them.

7. **`loop.call_soon_threadsafe(_enqueue)` in IEP1 capture thread.** The asyncio Queue must be accessed from the event loop thread only. `put_nowait` called directly from the capture thread is not thread-safe and causes `TypeError: A coroutine object is required` (BUG-010). The fix schedules `put_nowait` on the event loop via `call_soon_threadsafe`.

8. **Calibration must be verified before draft activation.** `floor_x`/`floor_y` columns in `global_tracking_history` are NOT NULL. If a camera config lacks a verified calibration, IEP2's `FloorProjector` returns `None` positions which cause INSERT failures or NULL values in tracking data.

9. **`camera_id` in `tracking_history` is the physical camera UUID (TEXT), not the `camera_config_id`.** IEP3 joins on this to find `camera_configs` and load homography. If IEP2 uses the wrong ID, IEP3 cannot project floor positions.

10. **IEP2 module entry point must use `python -m services.iep2_vision.main`**, not `python services/iep2_vision/main.py`. The `-m` flag adds the WORKDIR to `sys.path`, enabling `from services.iep2_vision.runtime import ...` and relative imports inside `runtime.py` to resolve correctly.

---

## 12. Testing Infrastructure

### 12.1 Documentation

| File | Scope |
|---|---|
| `docs/INFRA_TESTS.md` | Phases 0–2: infrastructure, database schema, service health checks. All commands in WIN/LIN/ORIN variants. |
| `docs/TESTING_GUIDE.md` | Phases 3–6: business data creation (UI-driven), edge pipeline validation, E2E, accuracy checks. |
| `docs/decisions/ADR-001-xack-before-processing.md` | Architecture decision: IEP3 XACK timing |
| `docs/operations/iep3-orphan-runbook.md` | Detecting and remediating orphaned global identities |
| `docs/security/mtls-migration.md` | mTLS migration path |

### 12.2 Automated Tests

| File | Type | Requires | Notes |
|---|---|---|---|
| `tests/unit/iep3/test_gate.py` | Unit | No external services | `cross_camera_gate` speed-limit invariants |
| `tests/unit/iep3/test_matcher.py` | Unit | No external services | `ReidMatcher` — Architecture Spec §10 invariants 1–3 |
| `tests/unit/iep3/test_selector.py` | Unit | No external services | `PositionSelector` — one row per global_id per batch |
| `tests/unit/iep3/test_state.py` | Unit | No external services | `StateManager` ACTIVE/LOST/EXITED transitions |
| `tests/e2e/test_iep3_reconciler.py` | Integration | PostgreSQL only | 3-camera reconciliation; no Redis/IEP1/IEP2 needed |
| `tests/e2e/test_full_pipeline.py` | Integration | Full stack | Requires EEP DEBUG_MODE, IEP1/IEP2 images |

Run unit tests:
```bash
# From repo root
docker run --rm -v $(pwd):/workspace -w /workspace \
  $(docker build -q tests/) \
  pytest tests/unit/iep3/ -v
```

### 12.3 Utility Scripts

| Script | Purpose |
|---|---|
| `scripts/generate_protos.sh` | Regenerate gRPC stubs; applies import path fixes |
| `scripts/check_env_example.py` | Verify `.env.example` covers all required `Field(...)` vars |
| `scripts/gen_dev_certs.sh` | Generate self-signed CA + EEP cert for dev TLS |
| `scripts/export_yolo_trt.py` | Export YOLOv8 to TensorRT FP16 (Jetson) |
| `scripts/export_osnet_trt.py` | Export OSNet x1.0 to TensorRT FP16 (Jetson) |
| `scripts/bootstrap-edge-k3s.sh` | Bootstrap Jetson with k3s and RetailVision stack |
| `services/eep/test_heartbeat.py` | Manual gRPC heartbeat tool (run inside EEP container) |

---

## 13. Known Bugs and Fixes

All bugs recorded in `ERROR_BACKLOG.md`. Summary:

| ID | Title | Status |
|---|---|---|
| BUG-001 | PgBouncer image not found on Docker Hub | Fixed |
| BUG-002 | YOLO/OSNet not buildable on x86/Intel (no Jetson/CUDA) | Fixed — CPU dev variants created |
| BUG-003 | grpcio 1.64.0 requires protobuf≥5.26.1, all services pinned to 4.25.3 | Fixed — upgraded to 5.27.2 |
| BUG-004 | `.env` REPLACE_ME placeholders override compose defaults → auth failure | Fixed |
| BUG-005 | EEP crash: `No module named 'alembic.config'` — migration dir shadows pip package | Fixed — migrations moved to `db_migrations/` |
| BUG-006 | IEP3 crash: `No module named 'pydantic'` — missing from requirements.txt | Fixed |
| BUG-007 | Alembic migration 0002 fails: `ADD CONSTRAINT IF NOT EXISTS` invalid SQL; compose on postgres:15 | Fixed — PG16, `DO $$ ... EXCEPTION WHEN duplicate_object` |
| BUG-008 | asyncpg + PgBouncer transaction mode → "prepared statement does not exist" | Fixed — session mode |
| BUG-009 | All uvicorn logs silenced after Alembic: `fileConfig` disables existing loggers | Fixed — `disable_existing_loggers=False` |
| BUG-010 | IEP1 capture thread dies after 1 frame: `run_coroutine_threadsafe(queue.put_nowait(...))` raises TypeError | Fixed — `loop.call_soon_threadsafe(_enqueue)` |
| BUG-011 | IEP2 `ModuleNotFoundError: No module named 'services'` — CMD runs script directly, not as module | Fixed — CMD changed to `python -m services.iep2_vision.main` |
| BUG-012 | IEP2 `ModuleNotFoundError: No module named 'boto3'` — `redis_source.py` imports boto3 at module level | Fixed — lazy import inside `make_s3_client()` |

---

## 14. Open Questions / TODOs

- **iep4_alerts, iep5_analytics, iep6_agent**: Services exist in compose with placeholder ports (8004, 8005, 8006) but implementations appear to be stubs. Not tested or documented.
- **`EMBEDDING_DIM` mismatch risk**: OSNet dev (ResNet-18) produces 512-dim. OSNet prod (OSNet x1.0) also 512-dim. Cross-dev/prod ReID matching is only valid if the same model family was used to generate embeddings in both local_centroids and the database.
- **Live Bridge stream**: `stream:iep2:live:{camera_id}` is only populated when `IEP2.live_stream_enabled=True`. This setting defaults to `False` and is not yet configurable via env var in IEP2 daemon mode.
- **mTLS**: Currently dev uses insecure gRPC (no TLS). Production migration path documented in `docs/security/mtls-migration.md` — not yet implemented in compose or k3s manifests.
- **Grafana dashboards**: Prometheus scrape targets and Grafana provisioning not yet configured. Both services start but show empty dashboards.
- **Employee ReID**: `employee_embeddings` table exists. IEP3 `is_employee` flag exists in `global_identities`. Exclusion logic in IEP3 for known employees not confirmed implemented.
- **Video sync across cameras**: For accurate cross-camera reconciliation, camera clocks must be synchronised within `WINDOW_SECONDS`. No NTP sync enforcement documented.
- **`GRACE_SECONDS` tuning**: Default 300 s. Stores with long customer dwell times (e.g. supermarkets) may need higher values to avoid premature orphan sweeps splitting one visit into two global IDs.
