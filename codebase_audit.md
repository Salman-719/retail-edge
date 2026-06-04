# RetailVision Codebase Audit
**Date:** 2026-06-04
**Scope:** EEP, IEP1–IEP3, Edge Agent, Live Bridge — post M1–M6 implementation
**Architecture:** k3s edge + cloud Kubernetes. EEP and IEP3 run on the server. IEP1 (camera ingestion daemon), IEP2 (per-camera vision workers), YOLO, and OSNet run on the edge device under k3s. A thin Edge Agent translates EEP gRPC commands into `k3s kubectl apply` operations.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Infrastructure & Schema](#2-infrastructure--schema)
3. [EEP — Enterprise Edge Platform](#3-eep--enterprise-edge-platform)
4. [IEP1 — Ingestion Daemon](#4-iep1--ingestion-daemon)
5. [IEP2 — Vision Worker](#5-iep2--vision-worker)
6. [IEP3 — Reconciliation Pipeline](#6-iep3--reconciliation-pipeline)
7. [Edge Agent](#7-edge-agent)
8. [Live Bridge](#8-live-bridge)
9. [gRPC Protocol](#9-grpc-protocol)
10. [Redis Topology](#10-redis-topology)
11. [Cross-Service Data Flows](#11-cross-service-data-flows)
12. [Deployment](#12-deployment)
13. [Environment Variables Reference](#13-environment-variables-reference)
14. [Dependency Versions](#14-dependency-versions)
15. [Architecture Decision Records](#15-architecture-decision-records)
16. [Known Gaps & Deferred Work](#16-known-gaps--deferred-work)

---

## 1. System Architecture

```
CLOUD  (Kubernetes / Docker Compose)
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  React Frontend :3000                                                   │
│         │ HTTP REST                                                     │
│  EEP  :8000 (REST) + :50051 (gRPC TLS)                                  │
│  FastAPI · SQLAlchemy asyncpg · APScheduler · grpc.aio                 │
│  · AgentAuthInterceptor (x-agent-token HMAC)                           │
│  Sends StartCamera/StopCamera to Edge Agent over gRPC stream            │
│                                                                         │
│  IEP3 Reconciliation (daemon, no port)                                  │
│  XREADGROUP iep3-{store_id} ← stream:iep2:batch_complete               │
│  BatchCoordinator → Reconciler (one asyncpg transaction/batch)         │
│  Writes: global_identities, global_local_mapping,                      │
│          global_embeddings, global_tracking_history                    │
│                                                                         │
│  Live Bridge :8010  (WebSocket → presigned S3 frame URLs)              │
│                                                                         │
│  PostgreSQL + PgBouncer · Server Redis · MinIO S3                       │
└──────────────────────┬──────────────────────────────────────────────────┘
                       │ gRPC TLS :50051
                       │ (edge dials out, stream stays open)
┌──────────────────────▼──────────────────────────────────────────────────┐
│  EDGE DEVICE  (k3s, Jetson / ARM64)                                     │
│                                                                         │
│  Edge Agent  (systemd service, not a container)                         │
│    grpc.aio TLS client · 30 s heartbeat · exponential-backoff reconnect │
│    StartCamera → k3s apply ConfigMap + Deployment → wait IEP2 SERVING   │
│              → AddCamera gRPC to IEP1 daemon                            │
│    StopCamera → RemoveCamera gRPC to IEP1 daemon → k3s delete resources │
│                                                                         │
│  IEP1 daemon (k3s Deployment, single pod for all cameras)               │
│    Receives AddCamera / RemoveCamera via gRPC control socket            │
│    Per-camera: RTSP/video → JPEG → /dev/shm/frames/{cam}/{ts}.jpg      │
│    60-second window → manifest → edge-local Redis XADD                  │
│                                                                         │
│  IEP2 vision (k3s Deployment per camera, created by Edge Agent)         │
│    XREADGROUP iep1-frames ← edge-local Redis stream:iep1:{camera_id}   │
│    tmpfs frame read → YOLO → ByteTrack → OSNet → homography → zones    │
│    INSERT tracking_history → XADD server-Redis stream:iep2:batch_complete│
│                                                                         │
│  YOLO service + OSNet service (GPU, ZMQ IPC unix sockets)               │
│  Edge-local Redis  127.0.0.1:6379  (loopback-only, ephemeral)           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

- **k3s edge model.** IEP1 is a single always-running daemon pod. IEP2 pods are created/deleted per-camera by the Edge Agent via the k3s API. No Docker socket is used anywhere.
- **Redis topology split.** `stream:iep1:{camera_id}` lives on edge-local Redis (loopback, ephemeral). `stream:iep2:batch_complete` lives on server Redis (persistent, TLS). IEP2 connects to both.
- **gRPC TLS + shared secret.** EEP uses `add_secure_port` (cert-manager certificate). Edge Agent verifies the CA. Each RPC carries `x-agent-token` header verified by `AgentAuthInterceptor`. Empty cert paths / empty secret = insecure dev mode.
- **XACK before reconciliation** (ADR-001). IEP3 XACKs each `batch_complete` message immediately on receipt, before calling `on_ready`. Compensating control is `orphan_sweep()` on startup and every `ORPHAN_SWEEP_INTERVAL_BATCHES` batches.
- **IEP3 expected cameras from DB.** `camera_configs` count is queried at startup and refreshed every `EXPECTED_CAMERAS_REFRESH_BATCHES` batches. No `EXPECTED_CAMERAS` env var.
- **Frame delivery via tmpfs, not S3.** IEP1 writes JPEGs to `/dev/shm/frames` (hostPath shared volume). IEP2 reads them by path from the manifest. No S3 round-trip on the edge device for frame delivery.

---

## 2. Infrastructure & Schema

### 2.1 Docker Compose Services

| Service | Build | Ports | Notes |
|---------|-------|-------|-------|
| `postgres` | postgres:15-alpine | 5432 | `schema.sql` as initdb; Alembic is authoritative migration path |
| `pgbouncer` | pgbouncer:1.22.1 | 5433→5432 | Transaction pooling; `ignore_startup_parameters=extra_float_digits` |
| `redis` | redis:7.2.4-alpine | 6379 | Persistent volume; used as server Redis in compose |
| `minio` | minio/minio | 9000, 9001 | S3-compatible; stores floor plans + (optional) frames |
| `prometheus` | prom/prometheus | 9090 | |
| `grafana` | grafana/grafana | 3001→3000 | |
| `eep` | ./services/eep | 8000, 50051 | Docker socket mounted; `REDIS_URL`, `AGENT_SECRET` |
| `iep1-daemon` | ./services/iep1_ingestion | — | Single daemon pod; `LOCAL_REDIS_URL` |
| `yolo-service` | ./services/yolo_service | 50052 | GPU; ZMQ IPC on shared `ipc-sockets` volume |
| `osnet-service` | ./services/osnet_service | 50053 | GPU; ZMQ IPC on shared `ipc-sockets` volume |
| `iep2_vision` | ./services/iep2_vision | — | `CAMERA_ID` required; `LOCAL_REDIS_URL` + `SERVER_REDIS_URL` |
| `iep3_reconciliation` | ./services/iep3_reconciliation | — | Daemon; `SERVER_REDIS_URL` from shared-config anchor |
| `live_bridge` | ./services/live_bridge | 8010 | `SERVER_REDIS_URL` |
| `edge_agent_dev` | ./services/edge_agent | — | Profile `edge`; `AGENT_SECRET` required |
| `iep2_dev` | ./services/iep2_vision | 8002 | Profile `dev`; FastAPI upload+WebSocket dev console |

**Shared config anchor** (`x-shared-config`):
```yaml
WINDOW_SECONDS: "60"
DATABASE_URL_SERVER: "postgresql://...@pgbouncer:5432/retailvision"
SERVER_REDIS_URL: "redis://redis:6379/0"
```

**Shared volumes:**
- `frame-store` (tmpfs) — IEP1 writes, IEP2 reads
- `ipc-sockets` (tmpfs) — ZMQ sockets between YOLO/OSNet and IEP2
- `iep1-sockets` (tmpfs) — gRPC unix sockets for IEP1 control/health

### 2.2 Database Schema

#### IEP1/IEP2 tables

**`tracking_history`**
```sql
CREATE TABLE tracking_history (
    id               UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_id        TEXT             NOT NULL,         -- physical_camera UUID as text
    local_id         UUID             NOT NULL,         -- uuid.UUID(int=bytetrack_id)
    timestamp_ms     BIGINT           NOT NULL,
    floor_x          DOUBLE PRECISION,                  -- NULL if no homography
    floor_y          DOUBLE PRECISION,
    zone_id          UUID             REFERENCES zones(id) ON DELETE SET NULL,
    bbox_confidence  REAL             NOT NULL,
    bbox_area        INTEGER          NOT NULL
);
CREATE INDEX idx_tracking_history_camera_ts ON tracking_history(camera_id, timestamp_ms);
CREATE INDEX idx_tracking_history_store_ts  ON tracking_history(store_id, timestamp_ms);
```

**`local_centroids`** — written by IEP2, read by IEP3
```sql
CREATE TABLE local_centroids (
    local_id         UUID  PRIMARY KEY,
    camera_id        TEXT  NOT NULL,
    store_id         UUID  NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    centroid         BYTEA NOT NULL,   -- float32[512] raw bytes
    updated_at_batch INT   NOT NULL
);
```

**`camera_schedules`**, **`edge_agents`**, **`camera_runtime_sessions`** — see `services/eep/schema.sql`.

#### IEP3 tables

**`global_identities`**
```sql
CREATE TABLE global_identities (
    global_id      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id       UUID         NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    first_seen_ts  BIGINT       NOT NULL,
    last_seen_ts   BIGINT       NOT NULL,
    last_floor_x   DOUBLE PRECISION,
    last_floor_y   DOUBLE PRECISION,
    state          VARCHAR(16)  NOT NULL DEFAULT 'active'
                                CHECK (state IN ('active','lost','exited')),
    lost_since_ts  BIGINT,
    entry_zone_id  UUID REFERENCES zones(id) ON DELETE SET NULL,
    exit_zone_id   UUID REFERENCES zones(id) ON DELETE SET NULL
);
```

**`global_local_mapping`**
```sql
CREATE TABLE global_local_mapping (
    id             BIGSERIAL PRIMARY KEY,
    global_id      UUID    NOT NULL REFERENCES global_identities(global_id) ON DELETE CASCADE,
    camera_id      TEXT    NOT NULL,
    local_id       UUID    NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    linked_at_ts   BIGINT  NOT NULL,
    last_seen_ts   BIGINT  NOT NULL,
    unlinked_at_ts BIGINT
);
-- Partial unique index: one active LocalID per (global_id, camera_id)
CREATE UNIQUE INDEX idx_glm_one_active_per_camera
    ON global_local_mapping(global_id, camera_id) WHERE is_active = TRUE;
```

**`global_embeddings`**
```sql
CREATE TABLE global_embeddings (
    global_id     UUID   NOT NULL REFERENCES global_identities(global_id) ON DELETE CASCADE,
    camera_id     TEXT   NOT NULL,
    centroid      BYTEA  NOT NULL,   -- float32[512]
    updated_at_ts BIGINT NOT NULL,
    PRIMARY KEY (global_id, camera_id)
);
```

**`global_tracking_history`**
```sql
CREATE TABLE global_tracking_history (
    id              BIGSERIAL        PRIMARY KEY,
    global_id       UUID             NOT NULL REFERENCES global_identities(global_id) ON DELETE CASCADE,
    store_id        UUID             NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    version_id      UUID             REFERENCES store_config_versions(id) ON DELETE SET NULL,
    batch_number    INT              NOT NULL,
    timestamp_ms    BIGINT           NOT NULL,
    floor_x         DOUBLE PRECISION NOT NULL,
    floor_y         DOUBLE PRECISION NOT NULL,
    zone_id         UUID             REFERENCES zones(id) ON DELETE SET NULL,
    source_camera   TEXT             NOT NULL,
    source_local_id UUID             NOT NULL,
    selection_score FLOAT4           NOT NULL
);
```

### 2.3 Redis Streams

#### Edge-local Redis — `stream:iep1:{camera_id}`

- **Written by:** IEP1 daemon (one XADD per 60-second window)
- **Read by:** IEP2 (one consumer per camera, group `iep2_workers`, consumer `iep2_{camera_id}`)
- **MAXLEN:** 1000 (approximate), set on every XADD
- **Payload:** JSON-encoded manifest

```json
{
  "status": "ok" | "offline",
  "batch_number": 3,
  "window_start_ms": 1717350060000,
  "window_end_ms":   1717350120000,
  "frame_count": 298,
  "expected_frames": 300,
  "gaps": [],
  "frames": [[<ts_ms>, "<tmpfs_path>"], ...]
}
```

Frame paths are tmpfs paths (e.g. `/dev/shm/frames/{camera_id}/{ts_ms}.jpg`), not S3 keys.

IEP2 XACK fires **after** `batch_complete` is published to server Redis and **after** `local_centroids` are flushed.

#### Server Redis — `stream:iep2:batch_complete`

- **Written by:** IEP2 (one XADD per batch per camera)
- **Read by:** IEP3 (group `iep3-{store_id}`, consumer `coordinator-1`)
- **MAXLEN:** 500 (approximate), set on every XADD

Fields: `camera_id`, `store_id`, `batch_number`, `window_start_ms`, `window_end_ms` (all bytes).

IEP3 XACKs **before** calling `on_ready` — see ADR-001.

#### Server Redis — `iep2:reload:{camera_config_id}` (pub/sub)

Published by EEP `draft.py` after homography calibration saves. IEP2 `_watch_reload_signals` coroutine subscribes and calls `projector.load()` to pick up new calibration without restart.

### 2.4 S3 / MinIO Object Layout

```
retailvision/
  floor-plans/{store_id}/{filename}
  calibration-files/{camera_config_id}/{filename}
  frames/{camera_id}/{batch_number}/{capture_ts_ms}.jpg   (optional, legacy path)
```

In the k3s deployment model, frames are delivered via tmpfs (not S3). S3 is used for floor plans, calibration images, and the optional Live Bridge frame delivery path.

---

## 3. EEP — Enterprise Edge Platform

**Location:** `services/eep/`
**Runtime:** FastAPI + uvicorn, Python 3.11, asyncpg connection pool
**Entry point:** `app/main.py` → `lifespan()` → `app = FastAPI(lifespan=lifespan)`

### 3.1 Startup Sequence

```python
async with engine.begin() as conn:
    await conn.run_sync(ModelBase.metadata.create_all)   # idempotent DDL
ensure_bucket()                                          # MinIO bucket init
await start_grpc_server()                                # gRPC on :50051
start_scheduler()                                        # APScheduler every 60 s
yield
stop_scheduler()
await stop_grpc_server(grace=5.0)
```

gRPC starts before APScheduler because scheduler tasks call `registry.send_command()`.

### 3.2 Configuration (`app/core/config.py`)

`pydantic_settings.BaseSettings`, `extra="ignore"`, env file `.env`.

| Field | Default | Description |
|-------|---------|-------------|
| `DATABASE_URL_EEP` | required | `postgresql+asyncpg://...` (SQLAlchemy async) |
| `WINDOW_SECONDS` | required | Must match IEP1/IEP2/IEP3 |
| `REDIS_URL` | `redis://redis:6379/0` | Server Redis |
| `JWT_SECRET` | required | Change in production |
| `S3_*` | required | MinIO / S3 credentials |
| `GRPC_PORT` | `50051` | gRPC listen port |
| `GRPC_SERVER_CERT_PATH` | `""` | Empty = insecure dev mode |
| `GRPC_SERVER_KEY_PATH` | `""` | Empty = insecure dev mode |
| `AGENT_SECRET` | `""` | Empty = no auth check (dev mode) |
| `DEBUG_MODE` | `False` | Enables `/api/debug/*` routes |

### 3.3 gRPC Server (`app/grpc_server/server.py`)

```python
async def start_grpc_server(port: int | None = None) -> grpc.aio.Server:
    _server = grpc.aio.server(interceptors=[AgentAuthInterceptor()])
    # TLS enabled only when both cert paths are set:
    if cert_path and key_path:
        _server.add_secure_port(f"[::]:{port}", _load_server_credentials())
    else:
        _server.add_insecure_port(f"[::]:{port}")   # dev mode
    await _server.start()
```

Includes `grpc_health.v1` and `grpc_reflection` services. Health set to `SERVING` on start.

### 3.4 Auth Interceptor (`app/grpc_server/interceptor.py`)

`AgentAuthInterceptor` implements `grpc.aio.ServerInterceptor`.

```python
_AGENT_SECRET: bytes = os.environ.get("AGENT_SECRET", "").encode("utf-8")

def _token_valid(provided: str) -> bool:
    if not _AGENT_SECRET:
        return False   # only called when secret is non-empty
    return hmac.compare_digest(provided.encode("utf-8"), _AGENT_SECRET)

async def intercept_service(self, continuation, handler_call_details):
    if not _AGENT_SECRET:           # dev mode — bypass auth entirely
        return await continuation(handler_call_details)
    token = metadata.get("x-agent-token", "")
    if not token or not _token_valid(token):
        abort UNAUTHENTICATED
    return await continuation(handler_call_details)
```

`hmac.compare_digest` is used for constant-time comparison (timing-attack safe).

### 3.5 Registry (`app/grpc_server/registry.py`)

```python
_connections: dict[str, asyncio.Queue] = {}  # store_id → queue

async def register(store_id) -> asyncio.Queue
def deregister(store_id)
async def send_command(store_id, msg: ControlMessage) -> bool
def connected_stores() -> list[str]
```

Module-level dict. On agent reconnect, the old queue is replaced. `send_command` returns `False` (never raises) if no agent is connected.

### 3.6 Servicer (`app/grpc_server/servicer.py`)

`Connect()` protocol:
1. First `AgentMessage` must be `Heartbeat` → `INVALID_ARGUMENT` otherwise
2. `store_id` extracted, registered in registry
3. `_reader` task: processes incoming messages (`_upsert_agent` on heartbeat)
4. `_writer` task: drains queue → `context.write(ControlMessage)`
5. `asyncio.wait(FIRST_COMPLETED)` — whichever finishes first cancels the other
6. `finally`: `registry.deregister()`, UPSERT `edge_agents.status='offline'`

`_upsert_agent`:
```sql
INSERT INTO edge_agents (store_id, status, last_heartbeat_at, agent_version, updated_at)
VALUES ($1::uuid, $2, $3, $4, $3)
ON CONFLICT (store_id) DO UPDATE SET
    status            = EXCLUDED.status,
    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
    agent_version     = COALESCE(EXCLUDED.agent_version, edge_agents.agent_version),
    updated_at        = EXCLUDED.updated_at
```

### 3.7 Scheduler & Orchestrator

**`app/tasks/camera_scheduler.py`**

`_running_cameras: set[tuple[str, str]]` — (store_id, camera_config_id). `evaluate_schedules()` fires every 60 s, checks per-store local time against schedule windows, calls `orchestrator.start/stop_camera_workers()`. `mark_running/mark_stopped()` called by the trigger endpoint to prevent double-starting.

**`app/core/orchestrator.py`**

`start_camera_workers(store_id, camera_config_id)`:
1. Load camera data: `camera_configs JOIN physical_cameras JOIN store_settings`
2. `registry.send_command(StartCamera)` — best-effort (warn if agent disconnected)
3. `iep2_docker.start_iep2(...)` via `run_in_executor` — legacy path, unused in k3s model

In the k3s model, EEP sends `StartCamera` to the Edge Agent which applies k3s resources. The `iep2_docker` path is retained for dev-on-compose compatibility only.

### 3.8 Draft Calibration Router (`app/api/routers/draft.py`)

After every calibration save (`compute_homography_calibration`, `upload_calibration_files`), publishes a homography reload signal:

```python
await redis.publish(f"iep2:reload:{config_id}", "homography")
```

IEP2 `_watch_reload_signals` coroutine subscribes on server Redis and calls `projector.load()` without restarting the pod.

### 3.9 Debug Router (`app/api/routers/debug.py`)

Only registered when `DEBUG_MODE=true`.

```
POST /api/debug/agent/command
Body: { store_id, camera_id, action: "start"|"stop", rtsp_url?, target_fps?, window_seconds? }
Response 202: { status: "sent", action, camera_id }
Response 404: { error: "no agent connected for store_id" }
Response 429: { error: "command queue full" }
```

---

## 4. IEP1 — Ingestion Daemon

**Location:** `services/iep1_ingestion/`
**Runtime:** Python 3.11, asyncio, gRPC server (control + health unix sockets)
**Model:** Single always-running daemon pod managing all cameras on the device. Camera lifecycle controlled via `AddCamera` / `RemoveCamera` gRPC from the Edge Agent.

### 4.1 Configuration (`app/daemon.py`)

```python
LOCAL_REDIS_URL  = os.environ.get("LOCAL_REDIS_URL", "redis://127.0.0.1:6379/0")
IEP1_CONTROL_SOCK = os.environ.get("IEP1_CONTROL_SOCK", "unix:///dev/shm/sockets/iep1_control.sock")
IEP1_HEALTH_SOCK  = os.environ.get("IEP1_HEALTH_SOCK",  "unix:///dev/shm/sockets/iep1_health.sock")
TMPFS_FRAME_ROOT  = os.environ.get("TMPFS_FRAME_ROOT",  "/dev/shm/frames")
```

`LOCAL_REDIS_URL` connects to the edge-local Redis on loopback. No server Redis connection.

### 4.2 Frame Delivery (tmpfs path)

IEP1 writes JPEG frames to `{TMPFS_FRAME_ROOT}/{camera_id}/{timestamp_ms}.jpg`. Paths (not S3 keys) are included in the manifest. IEP2 reads by path from the same hostPath volume. No network round-trip for frame delivery.

### 4.3 WindowPublisher (`app/publisher.py`)

```python
self._client.xadd(
    f"stream:iep1:{camera_id}",
    {"manifest": self._serialize(manifest)},
    maxlen=1000,
    approximate=True,
)
```

`maxlen=1000, approximate=True` is set on every XADD (prevents unbounded stream growth when IEP2 is slow/offline).

### 4.4 Frame Sources

**`RtspSource`** — `cv2.VideoCapture(rtsp_url)`. Real-time.

**`VideoFileSource`** — `cv2.VideoCapture(video_path)`. Decimation: `n = max(1, round(source_fps / target_fps))` — yields every n-th frame. Synthetic timestamps anchored to real wall clock.

---

## 5. IEP2 — Vision Worker

**Location:** `services/iep2_vision/`
**Runtime:** Python 3.11, asyncio, one process per camera
**Model:** One k3s Deployment per active camera, created by Edge Agent on `StartCamera`. In dev/compose, one container started by the compose CLI.

### 5.1 Configuration

IEP2 uses `pydantic_settings.BaseSettings` (daemon mode):

| Field | Default | Description |
|-------|---------|-------------|
| `CAMERA_ID` | required | `physical_cameras.id` UUID |
| `STORE_ID` | required | |
| `CAMERA_CONFIG_ID` | `""` | UUID from Edge Agent ConfigMap; enables homography reload signal |
| `WINDOW_SECONDS` | required | Must match IEP1 |
| `LOCAL_REDIS_URL` | required | Reads `stream:iep1:{camera_id}` from edge-local Redis |
| `SERVER_REDIS_URL` | required | Publishes `stream:iep2:batch_complete` to server Redis |
| `DATABASE_URL_SERVER` | required | `postgresql://...` (no `+asyncpg` prefix) |
| `YOLO_INPUT_SOCK` | required | ZMQ IPC socket path |
| `OSNET_INPUT_SOCK` | required | ZMQ IPC socket path |
| `TMPFS_FRAME_ROOT` | required | Base path for shared frame store |

TLS: if `SERVER_REDIS_URL` starts with `rediss://`, the Redis client adds `ssl_ca_certs` from `redis_ca_cert_path` (default `/etc/retailvision/certs/ca.crt`).

### 5.2 `RedisStreamFrameSource` (`ingest/redis_source.py`)

Reads from edge-local Redis (`LOCAL_REDIS_URL`). Group `iep2_workers`, consumer `iep2_{camera_id}`.

Two-phase delivery:
- **Phase A** (startup): `XREADGROUP ID="0"` — drain un-ACKed messages (crash recovery)
- **Phase B** (normal): `XREADGROUP ID=">"` — read new messages, block 2 s

`BUSYGROUP` on `XGROUP CREATE` is caught silently (idempotent group creation on restart).

XACK trade-off: fires **after** `batch_complete` is published to server Redis and centroids flushed. A crash mid-manifest replays the full manifest on Phase A restart.

### 5.3 `FloorProjector` (`projection/projector.py`)

`load(pool, camera_config_id)` — fetches homography matrix (JSONB `(3,3)` or flat `(9,)`) and zone polygons from PostgreSQL.

`project(x1, y1, x2, y2)` — numpy H @ [px, foot_y, 1]ᵀ, returns `(floor_x, floor_y)`.

`zone_of(floor_x, floor_y)` — Shapely Point.within(polygon) test.

Returns `None` if no calibration loaded; `floor_x/floor_y/zone_id` stored as `NULL`.

### 5.4 Homography Reload (`runtime.py`)

`_watch_reload_signals(camera_config_id, projector, pool, server_redis)` coroutine:
- Subscribes to `iep2:reload:{camera_config_id}` on server Redis pub/sub
- On `"homography"` message: `await projector.load(pool, UUID(camera_config_id))`
- Handles `CancelledError` cleanly; retries other errors after 5 s

### 5.5 Per-Batch Pipeline

```python
# After all frames in manifest processed:
await _flush_centroids(manager, persistence, batch_number)
await _publish_batch_complete(
    redis_client=server_redis,       # server Redis
    batch_number=batch_number,
    window_start_ms=..., window_end_ms=...,
)
await source.ack(message_id)         # edge-local Redis XACK
```

XADD on `stream:iep2:batch_complete` includes `maxlen=500, approximate=True`.

Ordering invariant: `tracking_history` → `local_centroids` → `batch_complete` XADD (server Redis) → IEP1 stream XACK (edge-local Redis).

### 5.6 Batch Keying

IEP2 publishes `window_start_ms` in the `batch_complete` message. IEP3's `BatchCoordinator` groups messages by `_batch_key(window_start_ms)` — rounds to the nearest window boundary. This is restart-safe: `window_start_ms` is monotonic, unlike `batch_number` which resets to 0 on IEP1 restart.

---

## 6. IEP3 — Reconciliation Pipeline

**Location:** `services/iep3_reconciliation/`
**Runtime:** Python 3.11, asyncio, long-running daemon, no HTTP port
**Entry point:** `python -m app.main`

### 6.1 Startup Sequence (`app/main.py`)

1. Load and validate settings (`Iep3Settings`)
2. Create asyncpg pool, verify DB (required tables present)
3. Create Redis client (`SERVER_REDIS_URL`), verify connectivity
4. `repo.get_expected_cameras_count(store_id)` — query `camera_configs` count from DB
5. `repo.orphan_sweep(store_id)` — startup cleanup (see §6.6)
6. `check_pel_health(redis_client, store_id)` — assert PEL is empty (see §6.7)
7. Construct `Reconciler` and `BatchCoordinator`
8. `coordinator.run()` — blocks until `SIGTERM`/`SIGINT`
9. Graceful shutdown: cancel coordinator, close Redis, close pool

### 6.2 Configuration (`app/settings.py`)

`Iep3Settings(BaseSettings)`, all via env vars, `extra="ignore"`.

| Field | Env var | Default | Notes |
|-------|---------|---------|-------|
| `store_id` | `STORE_ID` | required | One IEP3 instance per store |
| `window_seconds` | `WINDOW_SECONDS` | required | Must match IEP1/IEP2 |
| `database_url_server` | `DATABASE_URL_SERVER` | required | `postgresql://...` (no `+asyncpg`) |
| `server_redis_url` | `SERVER_REDIS_URL` | `redis://redis:6379/0` | |
| `reid_threshold` | `REID_THRESHOLD` | `0.75` | Cosine similarity cutoff |
| `max_speed_mps` | `MAX_SPEED_MPS` | `1.5` | Spatial gate |
| `grace_seconds` | `GRACE_SECONDS` | `300.0` | LOST → EXITED |
| `embedding_dim` | `EMBEDDING_DIM` | `512` | OSNet output dim |
| `centroid_ema_alpha` | `CENTROID_EMA_ALPHA` | `0.3` | EMA smoothing for embeddings |
| `coordinator_timeout_s` | `COORDINATOR_TIMEOUT_S` | `120.0` | Partial-batch timeout |
| `position_weight_area` | `POSITION_WEIGHT_AREA` | `0.7` | Canonical position scoring |
| `position_weight_conf` | `POSITION_WEIGHT_CONF` | `0.3` | Must sum to 1.0 with area |
| `expected_cameras_refresh_batches` | `EXPECTED_CAMERAS_REFRESH_BATCHES` | `10` | DB re-query cadence |
| `orphan_sweep_interval_batches` | `ORPHAN_SWEEP_INTERVAL_BATCHES` | `50` | Periodic sweep cadence |

`@model_validator(mode="after")` asserts `position_weight_area + position_weight_conf ≈ 1.0` (± 0.01).

### 6.3 BatchCoordinator (`app/coordinator.py`)

Consumer group `iep3-{store_id}`. `XREADGROUP BLOCK 5000 COUNT 16`.

`_batch_key(window_start_ms)` — rounds to nearest window boundary:
```python
window_ms = int(self._window_seconds * 1000)
return int(round(window_start_ms / window_ms) * window_ms)
```

State dicts keyed by `batch_key` (int), not `batch_number`. Restart-safe.

**XACK strategy:** fires immediately on message receipt, before `on_ready`. See ADR-001.

**Expected cameras:** queried from DB at startup, refreshed every `_refresh_batches` fires via:
```sql
SELECT COUNT(cc.id) FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
WHERE scv.store_id = $1 AND scv.status = 'active'
```

`check_pel_health` (module-level function):
- Calls `redis.xpending(STREAM, f"iep3-{store_id}")`
- Logs WARNING if `pending > 0` (indicates XACK was never sent — code bug)
- Returns `0` silently if consumer group doesn't exist yet (first startup)

### 6.4 Reconciler (`app/reconciler.py`)

Owns the single `pool.acquire()` / `conn.transaction()` per batch. Sub-components constructed once at `__init__`, reused across all batches. `PositionSelector._resolution_cache` is intentionally long-lived.

```python
async def process_batch(batch_number, window, reporting_cameras) -> dict:
    t0 = time.monotonic()
    async with self._pool.acquire() as conn:
        async with conn.transaction():
            known, new = await self._reader.classify(conn, window_start_ms, window_end_ms)
            n_new_globals = await self._matcher.link_new_locals(conn, ...)
            n_written = await self._selector.write_canonical_positions(conn, ...)
            cleanup_stats = await self._state.run_cleanup(conn, ...)
    # transaction committed
    reconcile_elapsed = time.monotonic() - t0
    self._batches_processed += 1

    # R7: skip orphan sweep if reconciliation used >80% of window budget
    if self._batches_processed % self._settings.orphan_sweep_interval_batches == 0:
        if reconcile_elapsed < self._settings.window_seconds * 0.8:
            await self._repo.orphan_sweep(self._store_id)
        else:
            logger.info("Skipping orphan sweep — reconciliation took %.1fs", reconcile_elapsed)
    return stats
```

Exceptions propagate to `BatchCoordinator._fire()` which catches, logs, and continues. Failed batch is skipped.

### 6.5 Repository (`app/repository.py`)

No ORM. All SQL uses asyncpg `$1…$N` positional params. Per-query timeouts:
- Transactional queries: `timeout=120.0` (inside batch transaction)
- Standalone queries: `timeout=30.0`

**New in M4-S3:**
- `get_expected_cameras_count(store_id) → int` — standalone
- `orphan_sweep(store_id) → tuple[int, int]` — transactional, structured logging

**`orphan_sweep`** cleans two categories in one transaction:
1. `global_identities` where `last_seen_ts == first_seen_ts` AND no `global_tracking_history` row
2. `local_centroids` where `store_id = $1` AND no active `global_local_mapping`

Returns `(deleted_globals, deleted_centroids)`. Logs `extra={"store_id", "deleted_globals", "deleted_centroids"}`.

### 6.6 Orphan Sweep Schedule

- **Startup:** always runs before consuming any messages (clears state from previous crash)
- **Periodic:** every `ORPHAN_SWEEP_INTERVAL_BATCHES` batches (default 50 ≈ 50 minutes at 1 batch/min)
- **Skip condition:** if `reconcile_elapsed >= window_seconds * 0.8` (avoid extending processing window)
- **Isolation:** always separate transaction, never nested inside reconciliation transaction

See `docs/operations/iep3-orphan-runbook.md` for SQL diagnostic queries.

### 6.7 PEL Health Check

`check_pel_health(redis_client, store_id)` in `coordinator.py`:
- Called once at IEP3 startup, after orphan sweep
- Non-empty PEL indicates XACK was not sent in a previous session — impossible in XACK-before-processing model, signals a code bug
- Logs WARNING if `pending > 0`; returns `0` if group doesn't exist (first run)

### 6.8 ReID Gates (`app/reid/gates.py`)

`cross_camera_gate(new_x, new_y, new_ts, last_x, last_y, last_ts, max_speed_mps) → bool`

- NULL `new_x/y` or `last_x/y` → `True` (uncalibrated camera, always passes)
- Negative `elapsed_s` → `True` + warning log (clock skew)
- Zero `elapsed_s` → `True` (simultaneous observations)
- Otherwise: `hypot(Δx, Δy) / elapsed_s ≤ max_speed_mps`

### 6.9 ReidMatcher (`app/reid/matcher.py`)

Operates inside the Reconciler's transaction. Loads all candidate globals and embeddings once before the per-LocalID loop. Mutates candidates in-place so GlobalIDs created for `local_id_i` are immediately available for `local_id_{i+1}`.

Cross-camera filter: exclude candidates with an active link on `obs.camera_id`. Then spatial gate. Then cosine similarity.

None check for `last_floor_x/y` is handled inside `cross_camera_gate` (returns `True` for NULL coords), not in the matcher pre-loop.

### 6.10 PositionSelector (`app/selection.py`)

Score: `position_weight_area * min(bbox_area/frame_px, 1.0) + position_weight_conf * bbox_confidence`

Uses `self._settings.position_weight_area` and `self._settings.position_weight_conf` (renamed from `selection_weight_*` in M4-S3).

Standalone DB calls (`get_camera_batch_info_bulk`, `get_camera_resolution`) acquire their own connections — correct: they read EEP-owned tables outside the IEP3 transaction.

### 6.11 StateManager (`app/state.py`)

Strict order inside transaction:
1. `ACTIVE → LOST`: GlobalIDs with no active link seen since `window_start_ms`
2. `LOST → EXITED`: `(window_end_ms - lost_since_ts) >= grace_ms`
3. `deactivate_mappings_for_globals` — before centroid deletion
4. `delete_centroids_for_globals`

LOST → ACTIVE reactivation handled exclusively by `ReidMatcher.reactivate_global()`.

---

## 7. Edge Agent

**Location:** `services/edge_agent/`
**Runtime:** Python 3.11, asyncio, grpc.aio client, no HTTP server
**Deployment:** systemd service on edge host (not a container)
**Entry point:** `python -m services.edge_agent.app.main`

### 7.1 Architecture Change from Docker Model

The Edge Agent no longer uses Docker socket or `docker_manager.py`. It now uses the k3s Kubernetes API via `kubernetes` Python client (`k8s_manager.py`). The `_tracked_cameras` dict is gone — k3s Deployments are the source of truth.

### 7.2 Configuration (`app/agent.py`)

| Var | Default | Description |
|-----|---------|-------------|
| `STORE_ID` | required | |
| `WINDOW_SECONDS` | `60` | |
| `IEP1_CONTROL_SOCK` | `unix:///dev/shm/sockets/iep1_control.sock` | gRPC to IEP1 daemon |
| `IEP1_HEALTH_SOCK` | `unix:///dev/shm/sockets/iep1_health.sock` | |
| `YOLO_HEALTH_SOCK` | `localhost:50052` | Inference service health via hostPort |
| `OSNET_HEALTH_SOCK` | `localhost:50053` | |
| `LOCAL_REDIS_URL` | `redis://localhost:6379/0` | Passed to IEP2 ConfigMaps |
| `SERVER_REDIS_URL` | `""` | Passed to IEP2 ConfigMaps |
| `DATABASE_URL_SERVER` | `""` | Passed to IEP2 ConfigMaps |
| `GRPC_CA_CERT_PATH` | `/etc/retailvision/certs/ca.crt` | CA cert for EEP TLS |
| `AGENT_SECRET` | `""` | Sent as `x-agent-token` metadata |
| `HEARTBEAT_INTERVAL_S` | `30` | |
| `IPC_SOCKETS_HOST_PATH` | `/dev/shm/sockets` | hostPath for IEP2 health sockets |

Required vars at startup (`_REQUIRED_VARS`): `EEP_GRPC_URL`, `STORE_ID`, `DATABASE_URL_SERVER`, `SERVER_REDIS_URL`, `AGENT_SECRET`.

### 7.3 TLS Fallback (`_load_channel_credentials`)

```python
def _load_channel_credentials() -> grpc.ChannelCredentials | None:
    if not GRPC_CA_CERT_PATH or not os.path.exists(GRPC_CA_CERT_PATH):
        return None   # dev mode — insecure channel
    with open(GRPC_CA_CERT_PATH, "rb") as f:
        return grpc.ssl_channel_credentials(root_certificates=f.read())
```

`_connect_to_eep` uses `secure_channel` when credentials are available, `insecure_channel` otherwise. `x-agent-token` metadata only sent when `AGENT_SECRET` is non-empty.

### 7.4 Startup Sequence (`_startup`)

1. `km.init_k8s_clients()` — load kubeconfig (blocking, via executor)
2. `_wait_for_health("yolo", YOLO_HEALTH_SOCK, timeout=120)` — poll gRPC health
3. `_wait_for_health("osnet", OSNET_HEALTH_SOCK, timeout=120)`
4. `_wait_for_health("iep1", IEP1_HEALTH_SOCK, timeout=60)`
5. `_restore_active_cameras()` — re-add cameras surviving Edge Agent restart

### 7.5 `_restore_active_cameras`

Reads k3s Deployments via `km.list_active_iep2_deployments()`. For each deployment, reads `RTSP_URL` from the associated ConfigMap and calls `_add_camera_to_iep1()`. If `RTSP_URL` is absent, skips with warning (EEP will resync).

This makes IEP1 the durable state store for camera-to-RTSP mapping across Edge Agent restarts.

### 7.6 `StartCamera` Handler

1. Build ConfigMap data: `{CAMERA_ID, STORE_ID, WINDOW_SECONDS, LOCAL_REDIS_URL, SERVER_REDIS_URL, DATABASE_URL_SERVER, RTSP_URL, TARGET_FPS}`
2. `km.apply_camera_configmap(camera_id, cm_data)` (via executor)
3. `km.apply_iep2_deployment(camera_id)` (via executor)
4. `_wait_for_iep2_health(camera_id, timeout=60)` — poll unix socket
5. `_add_camera_to_iep1(camera_id, ...)` — gRPC `AddCamera` to IEP1 daemon
6. Start `_watch_iep2_health` task per camera

### 7.7 `StopCamera` Handler

1. Cancel `_health_watchers[camera_id]`
2. gRPC `RemoveCamera` to IEP1 daemon
3. `km.delete_iep2(camera_id)` — delete Deployment + ConfigMap (via executor)

### 7.8 IEP1 Restart Recovery (`_iep1_health_watcher`)

Watches `grpc.health.v1.Watch` stream on IEP1 health socket. On `NOT_SERVING → SERVING` transition, calls `_restore_active_cameras()` to re-add all cameras lost to IEP1 in-memory state.

### 7.9 `k8s_manager.py`

All Kubernetes API calls use the `kubernetes` Python client, loaded via kubeconfig (`/etc/rancher/k3s/k3s.yaml` on edge). Runs in `_k8s_exec` thread pool (max_workers=4) — never on asyncio thread.

Key functions:
- `init_k8s_clients()` — loads kubeconfig, creates `AppsV1Api` and `CoreV1Api`
- `apply_camera_configmap(camera_id, data)` — create_or_patch ConfigMap in `retailvision` namespace
- `apply_iep2_deployment(camera_id)` — create_or_patch Deployment with `IEP2_IMAGE` from env
- `delete_iep2(camera_id)` — delete Deployment + ConfigMap
- `list_active_iep2_deployments()` — returns list of `{camera_id, ...ConfigMap fields}`
- `get_active_camera_ids()` — set of camera_ids with running Deployments
- `get_camera_k8s_status(camera_id)` — `"running"` | `"stopped"` from Pod phase

---

## 8. Live Bridge

**Location:** `services/live_bridge/`
**Runtime:** FastAPI + uvicorn, Python 3.11, asyncio
**Entry point:** `app/main.py` → `FastAPI()`

WebSocket endpoint `GET /ws/live/{camera_id}`. One `asyncio.Task` per camera, started on first client connection, stopped when last client disconnects. Presigns S3 URLs for `stream:iep2:live:{camera_id}` frames.

```python
SERVER_REDIS_URL = os.environ.get("SERVER_REDIS_URL", "redis://redis:6379/0")
```

Health endpoint: `GET /health` → `{"status": "ok"}`.

---

## 9. gRPC Protocol

**Proto:** `services/eep/proto/agent.proto` (canonical)
**Package:** `retailvision.agent.v1`
**Transport:** TLS (cert-manager in production, insecure in dev when cert paths are empty)
**Auth:** `x-agent-token` metadata, HMAC constant-time comparison. Bypassed when `AGENT_SECRET` is empty.

### 9.1 Service

```protobuf
service AgentService {
  rpc Connect(stream AgentMessage) returns (stream ControlMessage);
}
```

Single bidirectional streaming RPC. Edge dials out to EEP `:50051`; stream stays open for agent lifetime.

### 9.2 Messages

**Edge → Cloud:**
```protobuf
message AgentMessage { oneof payload { Heartbeat heartbeat = 1; CameraStatusReport camera_status = 2; } }
message Heartbeat     { string store_id; string agent_version; int64 timestamp_ms; }
message CameraStatusReport { string camera_id; string container_status; int64 timestamp_ms; }
```

**Cloud → Edge:**
```protobuf
message ControlMessage { oneof payload { StartCamera start_camera = 1; StopCamera stop_camera = 2; } }
message StartCamera    { string camera_id; string store_id; string rtsp_url; float target_fps;
                         float window_seconds; }
message StopCamera     { string camera_id; string store_id; }
```

`S3Config` is defined in the proto for legacy use; not used in the k3s deployment model (IEP2 pods receive S3 config via ConfigMap / env vars).

### 9.3 Protocol Invariants

- First `AgentMessage` must be `Heartbeat`. Server aborts with `INVALID_ARGUMENT` otherwise.
- `window_seconds` in `StartCamera` must equal `WINDOW_SECONDS` env var on IEP1 and IEP2.
- `camera_id` in `StartCamera` = `physical_cameras.id` UUID. **Not** `camera_configs.id`.
- Auth bypass: empty `AGENT_SECRET` on EEP disables the auth interceptor entirely. Empty `AGENT_SECRET` on edge agent sends no `x-agent-token` header.

Regenerate stubs:
```bash
docker compose run --rm eep python -m grpc_tools.protoc \
  -I services/eep/proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  services/eep/proto/agent.proto
# Fix import in agent_pb2_grpc.py; repeat for services/edge_agent/
```

---

## 10. Redis Topology

### 10.1 Edge-Local Redis

| Property | Value |
|----------|-------|
| Bind | `127.0.0.1` (loopback only, never network-accessible) |
| Port | `6379` |
| Persistence | None (`save ""`, `appendonly no`) |
| Max memory | `256mb`, `allkeys-lru` |
| Config | `infra/redis-local.conf` |
| Env var | `LOCAL_REDIS_URL` |

Contains: `stream:iep1:{camera_id}` (one per active camera). Ephemeral — device reboot clears all streams; IEP1 re-publishes current window on next startup.

### 10.2 Server Redis

| Property | Value |
|----------|-------|
| Bind | All interfaces (cloud host) |
| Port | `6379` (plain) / `6380` (TLS in k3s deployment) |
| TLS | `rediss://` scheme triggers `ssl_ca_certs` in IEP2 + IEP3 |
| Env var | `SERVER_REDIS_URL` |

Contains:
- `stream:iep2:batch_complete` (global, all stores)
- `stream:iep2:live:{camera_id}` (optional, for Live Bridge)
- `iep2:reload:{camera_config_id}` (pub/sub channel, transient)

### 10.3 Per-Service Redis Assignment

| Service | Redis URL env var | Target |
|---------|-------------------|--------|
| IEP1 | `LOCAL_REDIS_URL` | Edge-local |
| IEP2 (reads IEP1) | `LOCAL_REDIS_URL` | Edge-local |
| IEP2 (publishes batch_complete) | `SERVER_REDIS_URL` | Server |
| IEP2 (homography reload pub/sub) | `SERVER_REDIS_URL` | Server |
| IEP3 | `SERVER_REDIS_URL` | Server |
| EEP | `REDIS_URL` | Server (Redis-backed `_running_cameras`) |
| Live Bridge | `SERVER_REDIS_URL` | Server |
| Edge Agent | n/a (passes via ConfigMap) | n/a |

In Docker Compose dev mode, both Redis URL env vars point to the same Redis instance.

---

## 11. Cross-Service Data Flows

### 11.1 Schedule → Camera Start

```
APScheduler (60 s) → evaluate_schedules()
  → _should_run(row, now_local_tz)
  → orchestrator.start_camera_workers(store_id, camera_config_id)
      → _load_camera_data(): camera_configs JOIN physical_cameras JOIN store_settings
      → registry.send_command(StartCamera{camera_id, rtsp_url, target_fps, ...})
          → asyncio.Queue → _writer task → gRPC context.write()
              ── gRPC TLS stream ──────────────────────────────────
              Edge Agent _handle_control()
                → k8s_manager.apply_camera_configmap(camera_id, {...})
                → k8s_manager.apply_iep2_deployment(camera_id)
                → _wait_for_iep2_health(camera_id, timeout=60)
                → _add_camera_to_iep1(camera_id, rtsp_url, ...)
                    → gRPC AddCamera to IEP1 daemon unix socket
                        IEP1: RTSP → JPEG → /dev/shm/frames/ → XADD stream:iep1:{cam}
```

### 11.2 IEP1 → IEP2 → IEP3 Frame Pipeline

```
IEP1: RTSP frame → /dev/shm/frames/{cam}/{ts}.jpg
      every 60 s: manifest → edge-local Redis XADD stream:iep1:{cam}

IEP2: XREADGROUP iep1-frames stream:iep1:{cam}
      manifest → read /dev/shm/frames paths (tmpfs, no network)
      → YOLO (ZMQ unix socket) → ByteTrack → OSNet (ZMQ unix socket)
      → homography → INSERT tracking_history
      → UPSERT local_centroids
      → server Redis XADD stream:iep2:batch_complete  (maxlen=500)
      → edge-local Redis XACK stream:iep1:{cam}

IEP3: server Redis XREADGROUP iep3-{store_id} stream:iep2:batch_complete
      → XACK immediately (ADR-001)
      → BatchCoordinator: collect cameras, fire when all N reported (or timeout)
      → Reconciler (one asyncpg transaction):
          BatchReader.classify → ReidMatcher.link_new_locals
          → PositionSelector.write_canonical_positions
          → StateManager.run_cleanup
      → periodic orphan_sweep (every 50 batches, skip if >80% window used)
```

### 11.3 Homography Calibration Reload

```
EEP draft.py: POST /calibration/homography → save to DB → db.commit()
  → redis.publish("iep2:reload:{config_id}", "homography")

IEP2 _watch_reload_signals coroutine (server Redis pub/sub):
  → projector.load(pool, UUID(camera_config_id))
  → homography matrix + zones refreshed in-memory
  (no IEP2 pod restart required)
```

### 11.4 Heartbeat → DB

```
Edge Agent heartbeat loop (30 s):
  → XADD AgentMessage{heartbeat} to _outgoing queue
  → _request_generator yields → stub.Connect gRPC stream
      EEP servicer._reader:
        Heartbeat → _upsert_agent(store_id, "online")
          → asyncpg INSERT INTO edge_agents ON CONFLICT DO UPDATE
On disconnect:
  servicer.Connect finally → _upsert_agent(store_id, "offline")
```

---

## 12. Deployment

### 12.1 Local Docker Compose

Default: insecure gRPC (no certs), no auth. All services on same Docker network.

```bash
docker compose up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge
docker compose --profile edge up -d iep1-daemon yolo-service osnet-service edge_agent_dev
```

Dev overrides (DEBUG_MODE, live reload):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### 12.2 Cloud — Server (Helm)

Chart: `charts/retailvision/` (see `Chart.yaml`, `values.yaml`, `values.staging.yaml`, `values.production.yaml`).

Templates:
| Template | Resource |
|----------|----------|
| `namespace.yaml` | Namespace `retailvision` |
| `rbac.yaml` | ServiceAccounts for `eep`, `iep3` |
| `eep-certificate.yaml` | cert-manager Certificate → Secret `eep-tls` |
| `external-secrets.yaml` | ExternalSecret pulling secrets from secrets manager |
| `eep-deployment.yaml` | Deployment, replicas=2, anti-affinity, TLS volume mount |
| `eep-service.yaml` | ClusterIP :8000 + LoadBalancer :50051 |
| `iep3-statefulset.yaml` | One StatefulSet per store in `iep3.stores[]`, replicas=1 always |
| `iep3-service.yaml` | Headless service per StatefulSet |
| `pgbouncer-deployment.yaml` | Deployment + ClusterIP service |
| `redis-statefulset.yaml` | StatefulSet + TLS ConfigMap + ClusterIP service :6380 |

**R2 invariant:** IEP3 must be a StatefulSet (not Deployment) — multiple replicas would split the in-memory candidate pool. `replicas: 1` is enforced.

**R1 invariant:** `eep.replicas > 1` requires Redis-backed `_running_cameras` (M4-S1). Do not scale EEP before that is deployed.

### 12.3 Edge Device — k3s Bootstrap

Script: `scripts/bootstrap-edge-k3s.sh <store_uuid> <version> <eep_host> <agent_secret>`

Steps:
1. NTP sync (mandatory — stream timestamps must align)
2. k3s install with `--bind-address=127.0.0.1` (API server loopback-only)
3. NVIDIA container toolkit + device plugin
4. Create shared host paths (`/dev/shm/sockets`, `/dev/shm/frames`)
5. Apply `infra/edge/base/` manifests (namespace, RBAC, yolo, osnet, iep1-daemon)
6. Write `/etc/retailvision/edge-agent.env`
7. Install `retailvision-edge-agent.service` systemd unit

Edge base manifests:
| File | Content |
|------|---------|
| `namespace.yaml` | Namespace `retailvision` |
| `rbac.yaml` | ServiceAccount + Role + RoleBinding for edge-agent |
| `yolo-service.yaml` | Deployment, GPU limit `nvidia.com/gpu: 1`, ZMQ unix socket IPC |
| `osnet-service.yaml` | Same pattern as yolo-service |
| `iep1-daemon.yaml` | Deployment, `hostNetwork: true` (for loopback Redis access), `LOCAL_REDIS_URL` |

**`hostNetwork: true` on IEP1:** Required because IEP1 connects to `redis://127.0.0.1:6379`. Inside a k3s pod, `127.0.0.1` is the pod's own loopback. `hostNetwork: true` makes the pod share the host's network namespace so `127.0.0.1` reaches the host Redis instance.

---

## 13. Environment Variables Reference

### EEP

| Var | Default | Required | Description |
|-----|---------|----------|-------------|
| `DATABASE_URL_EEP` | — | yes | `postgresql+asyncpg://...` (SQLAlchemy async) |
| `WINDOW_SECONDS` | — | yes | Must match IEP1/IEP2/IEP3 |
| `REDIS_URL` | `redis://redis:6379/0` | | Server Redis |
| `JWT_SECRET` | — | yes | Change in production |
| `AGENT_SECRET` | `""` | | Empty = no auth (dev mode) |
| `GRPC_SERVER_CERT_PATH` | `""` | | Empty = insecure gRPC (dev mode) |
| `GRPC_SERVER_KEY_PATH` | `""` | | Empty = insecure gRPC (dev mode) |
| `GRPC_PORT` | `50051` | | |
| `DEBUG_MODE` | `false` | | Enables `/api/debug/*` — disable in production |
| `S3_ENDPOINT_URL/ACCESS_KEY/SECRET_KEY/BUCKET` | — | yes | MinIO / S3 |

### IEP1 Ingestion Daemon

| Var | Default | Description |
|-----|---------|-------------|
| `LOCAL_REDIS_URL` | `redis://127.0.0.1:6379/0` | Edge-local Redis (loopback) |
| `IEP1_CONTROL_SOCK` | `unix:///dev/shm/sockets/iep1_control.sock` | |
| `IEP1_HEALTH_SOCK` | `unix:///dev/shm/sockets/iep1_health.sock` | |
| `TMPFS_FRAME_ROOT` | `/dev/shm/frames` | Shared frame store base path |

### IEP2 Vision Worker

| Var | Required | Description |
|-----|----------|-------------|
| `CAMERA_ID` | yes | `physical_cameras.id` UUID |
| `STORE_ID` | yes | |
| `CAMERA_CONFIG_ID` | | Enables homography reload signal subscription |
| `WINDOW_SECONDS` | yes | Must match IEP1 |
| `LOCAL_REDIS_URL` | yes | Reads IEP1 stream from edge-local Redis |
| `SERVER_REDIS_URL` | yes | Publishes `batch_complete` to server Redis |
| `DATABASE_URL_SERVER` | yes | `postgresql://...` (no `+asyncpg`) |
| `YOLO_INPUT_SOCK` | yes | ZMQ IPC socket |
| `OSNET_INPUT_SOCK` | yes | ZMQ IPC socket |
| `TMPFS_FRAME_ROOT` | yes | Base path for shared frame store |

### IEP3 Reconciliation

| Var | Default | Description |
|-----|---------|-------------|
| `STORE_ID` | required | One IEP3 per store |
| `WINDOW_SECONDS` | required | Must match IEP1/IEP2 |
| `DATABASE_URL_SERVER` | required | `postgresql://...` (no `+asyncpg`) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | |
| `REID_THRESHOLD` | `0.75` | Cosine similarity cutoff |
| `MAX_SPEED_MPS` | `1.5` | Spatial gate |
| `GRACE_SECONDS` | `300.0` | LOST → EXITED |
| `EMBEDDING_DIM` | `512` | |
| `CENTROID_EMA_ALPHA` | `0.3` | EMA smoothing |
| `COORDINATOR_TIMEOUT_S` | `120.0` | Partial-batch timeout |
| `POSITION_WEIGHT_AREA` | `0.7` | Must sum to 1.0 with CONF |
| `POSITION_WEIGHT_CONF` | `0.3` | |
| `EXPECTED_CAMERAS_REFRESH_BATCHES` | `10` | DB camera-count re-query cadence |
| `ORPHAN_SWEEP_INTERVAL_BATCHES` | `50` | Periodic sweep cadence |

### Edge Agent

| Var | Required | Default | Description |
|-----|----------|---------|-------------|
| `EEP_GRPC_URL` | yes | | `host:50051` |
| `STORE_ID` | yes | | |
| `AGENT_SECRET` | yes | | Must match EEP's `AGENT_SECRET`; empty = no token sent (dev) |
| `GRPC_CA_CERT_PATH` | | `/etc/retailvision/certs/ca.crt` | Missing file = insecure channel (dev) |
| `SERVER_REDIS_URL` | yes | | Passed to IEP2 ConfigMaps |
| `DATABASE_URL_SERVER` | yes | | Passed to IEP2 ConfigMaps |
| `LOCAL_REDIS_URL` | | `redis://localhost:6379/0` | Passed to IEP1 |
| `HEARTBEAT_INTERVAL_S` | | `30` | |

### Live Bridge

| Var | Default | Description |
|-----|---------|-------------|
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | Reads `stream:iep2:live:{camera_id}` |
| `S3_ENDPOINT_URL/ACCESS_KEY/SECRET_KEY/BUCKET` | required | Frame URL presigning |
| `PRESIGNED_URL_EXPIRY` | `30` | Seconds |

---

## 14. Dependency Versions

### EEP

```
fastapi==0.115.0
uvicorn[standard]==0.30.1
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
redis[asyncio]==5.0.4
boto3==1.34.69
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
pydantic-settings==2.2.1
apscheduler==3.10.4
grpcio==1.64.0
grpcio-tools==1.64.0
grpcio-health-checking==1.64.0
grpcio-reflection==1.64.0
docker==7.1.0
shapely==2.0.4
```

### IEP1

```
opencv-python-headless==4.9.0.80
redis==5.0.1
grpcio==1.64.0     # IEP1 gRPC control/health server
numpy==1.26.4
```

### IEP2

```
opencv-python-headless==4.9.0.80
ultralytics           # YOLOv8
boxmot>=10.0.0        # ByteTrack
asyncpg==0.29.0
shapely==2.0.4
redis[asyncio]==5.0.3
pydantic-settings==2.2.1
grpcio==1.64.0
numpy==1.26.4
```

### IEP3

```
asyncpg==0.29.0
redis[asyncio]==5.0.3
numpy==1.26.4
pydantic-settings==2.2.1
```

### Edge Agent

```
grpcio==1.64.0
grpcio-tools==1.64.0
grpcio-health-checking==1.64.0
kubernetes==29.0.0
```

### Tests

```
pytest
pytest-asyncio==0.23.6
asyncpg
redis[asyncio]
boto3
```

---

## 15. Architecture Decision Records

### ADR-001: XACK Before Processing in IEP3

**Status:** Accepted
**Location:** `docs/decisions/ADR-001-xack-before-processing.md`

IEP3 XACKs `batch_complete` messages immediately on receipt, before calling `on_ready`. This means a crash between XACK and reconciliation silently loses the batch (no retry).

**Rationale:** Reconciliation is not idempotent (creates GlobalIDs, FSM transitions). Making it idempotent requires deterministic GlobalID derivation or stored batch-key deduplication — neither is worth the complexity for the expected crash frequency.

**Compensating controls:**
1. `orphan_sweep()` on every IEP3 startup
2. `orphan_sweep()` every `ORPHAN_SWEEP_INTERVAL_BATCHES` batches
3. Orphan sweep skipped when reconciliation > 80% of window budget (R7)
4. `check_pel_health()` on startup (non-empty PEL = code bug)
5. Orphan sweep always in a separate transaction from reconciliation

**Failure mode analysis:**
- Crash after XACK, before `on_ready`: no DB writes → no orphans
- Crash inside transaction: PostgreSQL rolls back → no orphans
- Crash after COMMIT: full success, no orphans
- Only orphan source: `global_identity` created, crash before `global_tracking_history` written

---

## 16. Known Gaps & Deferred Work

### Resolved since last audit (M1–M6)

| Item | Resolution |
|------|-----------|
| No TLS on gRPC | M4-S2: cert-manager cert + `add_secure_port`; dev fallback to insecure |
| No auth on gRPC | M4-S2: `AgentAuthInterceptor` with HMAC constant-time compare |
| `_running_cameras` resets on EEP restart | M4-S1: Redis-backed `_running_cameras` set |
| `EXPECTED_CAMERAS` static env var | M4-S3: dynamic query from `camera_configs` + periodic refresh |
| IEP3 settings as dataclass | M4-S3: migrated to `pydantic_settings.BaseSettings` |
| No orphan sweep robustness | M4-S3 + M5-S2: per-query timeouts, structured logging, PEL check, R7 timing skip |
| Redis topology not split | M5-S1: edge-local (`LOCAL_REDIS_URL`) vs server (`SERVER_REDIS_URL`) |
| No homography live reload | M5-S1: pub/sub signal in `draft.py` + `_watch_reload_signals` in IEP2 |
| Docker socket model on edge | M6-S2: replaced by k3s + `k8s_manager.py` + `edge_agent.py` rewrite |
| Batch keying by `batch_number` | M4-S3: switched to `window_start_ms`-rounded keying (restart-safe) |
| XADD without MAXLEN | M5-S1: all XADD calls now include `maxlen=N, approximate=True` |

### Remaining gaps

| Gap | Location | Impact | Mitigation |
|-----|----------|--------|-----------|
| mTLS not yet implemented | EEP gRPC | Shared secret is less secure than per-device certs | Migration plan at `docs/security/mtls-migration.md` |
| `_running_cameras` in EEP not Redis-backed in all code paths | `camera_scheduler.py` | EEP restart may cause schedule re-evaluation to start cameras that were stopped manually | Acceptable for current scale; Redis persistence is the M4-S1 fix |
| IEP2 `run_from_iep1` legacy path still uses single `redis_url` | `iep2_vision/runtime.py` | Only used in dev/test path, not production daemon path | Non-critical |
| No Prometheus metrics | All IEP1–IEP3 | Reconciliation latency, ReID match rate, partial batch rate invisible | Add `prometheus_client` counters to `reconciler.py` in a future observability sprint |
| `local_centroids` orphan sweep doesn't filter by `store_id` in the legacy code path | Resolved by store_id filter added in M5-S2; schema uncertainty about `store_id` column on old rows | Low — orphan sweep is safe to run without the filter (deletes any orphaned centroid regardless of store) | Verify `local_centroids.store_id` column exists before running store-filtered sweep |
| IEP3 `coordinator_timeout_s` default `120s` diverges from spec's `10s` | `settings.py` | Longer timeout means partial batches fire later — safer for multi-camera deployments | Intentional deviation; spec default was too aggressive |
| k3s on x86 dev machines | `infra/edge/base/` | YOLO/OSNet Dockerfiles use Jetson/ARM64 JetPack base image | Use `Dockerfile.dev` (CPU fallback) on x86 |
| IEP4/IEP5/IEP6 skeleton services | `services/iep4_alerts/`, etc. | No implementation logic — start and idle | Planned for future phases |
