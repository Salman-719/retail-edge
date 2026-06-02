# RetailVision Codebase Audit
**Date:** 2026-06-02  
**Scope:** EEP, IEP1, IEP2, Edge Agent — post Phase 1–8 implementation  
**Architecture:** Edge-cloud hybrid. EEP (server) orchestrates; IEP1 runs on the edge device (managed by the Edge Agent); IEP2 runs on the server alongside EEP (managed by EEP via the local Docker socket); Edge Agent brokers cloud→edge commands.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Infrastructure & Schema](#2-infrastructure--schema)
3. [EEP — Enterprise Edge Platform](#3-eep--enterprise-edge-platform)
4. [IEP1 — Ingestion Pipeline](#4-iep1--ingestion-pipeline)
5. [IEP2 — Vision Pipeline](#5-iep2--vision-pipeline)
6. [Edge Agent](#6-edge-agent)
7. [gRPC Protocol](#7-grpc-protocol)
8. [Cross-Service Data Flows](#8-cross-service-data-flows)
9. [Environment Variables Reference](#9-environment-variables-reference)
10. [Dependency Versions](#10-dependency-versions)
11. [Known Gaps & Next Steps](#11-known-gaps--next-steps)

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  SERVER HOST  (Docker Compose in dev; cloud/k8s in prod)                 │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  EEP  :8000 (HTTP/REST) + :50051 (gRPC)                           │  │
│  │  FastAPI + SQLAlchemy asyncpg + APScheduler + grpc.aio             │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │  │
│  │  │ REST API    │  │ gRPC Server  │  │ APScheduler              │  │  │
│  │  │ (30+ routes)│  │ AgentService │  │ evaluate_schedules 60 s  │  │  │
│  │  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────────┘  │  │
│  │         └────────────────┴──────────────────────┘                  │  │
│  │                          │                                          │  │
│  │         orchestrator.start/stop_camera_workers()                   │  │
│  │           ├─ registry.send_command() → gRPC → Edge Agent → IEP1   │  │
│  │           └─ iep2_docker.start_iep2() → local Docker socket        │  │
│  └────────────────────────────────────┬─────────────────────────────┘  │
│                                        │ /var/run/docker.sock           │
│  ┌─────────────────────────────────────▼───────────────────────────┐   │
│  │  iep2_{store}_{cam}   services/iep2_vision/                     │   │
│  │  RedisStreamFrameSource (XREADGROUP iep2_workers)               │   │
│  │    → S3 fetch JPEG → YOLOv8 → ByteTrack                         │   │
│  │    → LocalIdentityManager (ReID)                                │   │
│  │    → FloorProjector (homography + shapely zones)                │   │
│  │    → asyncpg INSERT tracking_history                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  PostgreSQL :5432     Redis :6379     MinIO S3 :9000                    │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │ gRPC bidirectional stream :50051
                                  │ (edge dials out, stream stays open)
                                  │ IEP1 → MinIO S3  (server-reachable endpoint)
                                  │ IEP1 → Redis     (server-reachable endpoint)
┌─────────────────────────────────▼────────────────────────────────────────┐
│  EDGE DEVICE                                                             │
│                                                                          │
│  Edge Agent  services/edge_agent/                                        │
│    grpc.aio client · 30 s heartbeat · exponential-backoff reconnect      │
│    _handle_control() → docker_manager.start/stop_iep1()                  │
│                │ /var/run/docker.sock (edge host Docker daemon)           │
│  ┌─────────────▼──────────────────────────────────────────────────┐     │
│  │  iep1_{store}_{cam}   services/iep1_ingestion/                 │     │
│  │  Camera (RTSP or video file)                                   │     │
│  │    → RtspSource / VideoFileSource                              │     │
│  │    → S3Uploader (JPEG frames → MinIO S3 on server)            │     │
│  │    → WindowAccumulator (60 s window)                           │     │
│  │    → WindowPublisher (Redis XADD on server)                    │     │
│  └────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **IEP1 runs on the edge device.** The Edge Agent manages it via the edge host's Docker socket. IEP1 uploads frames to MinIO S3 and publishes manifests to Redis — both of which are reachable from the edge device over the network.
- **IEP2 runs on the server alongside EEP.** EEP starts IEP2 containers via the server's local Docker socket (mounted at `/var/run/docker.sock`). IEP2 reads from Redis and writes to PostgreSQL, both of which are co-located on the same host.
- gRPC bidirectional stream (not polling) keeps the server-edge link alive. Edge dials out to `:50051` — no inbound firewall rules needed on the edge device.
- Redis Streams with `XREADGROUP` give at-least-once delivery for IEP1 manifests. XACK fires after the DB write completes, not before.
- `tracking_history` rows use `camera_id TEXT` (not UUID FK) to decouple IEP2 from EEP's camera_configs schema.
- `local_id` in `tracking_history` is a UUID derived deterministically from an int via `uuid.UUID(int=local_id)`. The int comes from `LocalIdentityManager`. The UUID form satisfies the PK/indexing needs.

---

## 2. Infrastructure & Schema

### 2.1 Docker Compose Services

| Service | Image / Build | Ports | Key Config |
|---------|--------------|-------|------------|
| `postgres` | postgres:15-alpine | 5432 | schema.sql mounted as initdb |
| `redis` | redis:7-alpine | 6379 | persistent volume |
| `minio` | minio/minio:latest | 9000 (S3), 9001 (console) | S3-compatible object store |
| `prometheus` | prom/prometheus:v2.51.0 | 9090 | |
| `grafana` | grafana/grafana:10.4.1 | 3001→3000 | |
| `frontend` | ./frontend | 3000→80 | |
| `eep` | ./services/eep | 8000 (HTTP), 50051 (gRPC) | Docker socket mounted, DEBUG_MODE=true |
| `iep1_ingestion` | ./services/iep1_ingestion | — | started by Edge Agent on demand |
| `iep2_vision` | ./services/iep2_vision | — | started by EEP orchestrator on demand |

EEP mounts `/var/run/docker.sock` to manage IEP2 containers. `IEP2_IMAGE` and `DOCKER_NETWORK` are env vars.

### 2.2 Database Schema — Domain 9 Tables (new)

**`tracking_history`**

```sql
CREATE TABLE IF NOT EXISTS tracking_history (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_id        TEXT        NOT NULL,          -- physical_camera UUID as text
    local_id         UUID        NOT NULL,          -- from uuid.UUID(int=local_id)
    timestamp_ms     BIGINT      NOT NULL,
    floor_x          DOUBLE PRECISION,              -- NULL if no homography
    floor_y          DOUBLE PRECISION,              -- NULL if no homography
    zone_id          UUID        REFERENCES zones(id) ON DELETE SET NULL,
    bbox_confidence  REAL        NOT NULL,
    bbox_area        INTEGER     NOT NULL
);
CREATE INDEX idx_tracking_history_camera_ts ON tracking_history(camera_id, timestamp_ms);
CREATE INDEX idx_tracking_history_store_ts  ON tracking_history(store_id, timestamp_ms);
```

**`camera_schedules`**

```sql
CREATE TABLE IF NOT EXISTS camera_schedules (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_config_id UUID        NOT NULL REFERENCES camera_configs(id) ON DELETE CASCADE,
    days_of_week     INTEGER[]   NOT NULL,          -- 0=Mon … 6=Sun (weekday() convention)
    start_time       TIME        NOT NULL,
    end_time         TIME        NOT NULL,
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`edge_agents`**

```sql
CREATE TABLE IF NOT EXISTS edge_agents (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id          UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE UNIQUE,
    status            TEXT        NOT NULL CHECK (status IN ('online', 'offline')) DEFAULT 'offline',
    last_heartbeat_at TIMESTAMPTZ,
    agent_version     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`UNIQUE` on `store_id` is the conflict target for the UPSERT in `_upsert_agent()`.

### 2.3 Redis Streams

**Stream name:** `stream:iep1:{camera_id}`  
**Consumer group:** `iep2_workers`  
**Consumer name:** `iep2_{camera_id}` (per IEP2 process)

Each message payload is a JSON-encoded manifest:

```json
{
  "status": "ok" | "offline",
  "batch_number": 3,
  "window_start_ms": 1717350060000,
  "window_end_ms": 1717350120000,
  "frame_count": 298,
  "expected_frames": 300,
  "gaps": [],
  "frames": [[<ts_ms>, "<s3_key>"], ...]
}
```

IEP2 uses two-phase delivery:
- **Phase A** (crash recovery): XREADGROUP with `ID="0"` drains un-ACKed messages from before restart.
- **Phase B** (normal): XREADGROUP with `ID=">"` reads new messages, blocking 2 s per call.

XACK fires at manifest level — after all frames in the manifest have been processed and written to the DB.

### 2.4 S3 Object Layout

```
retailvision/
  frames/{camera_id}/{batch_number}/{capture_ts_ms}.jpg
```

IEP1 uploads JPEG frames. IEP2 fetches them by key from the manifest. IEP1 deletes frames 300 s after the batch closes (TTL cleanup via `_pending_cleanup` deque).

---

## 3. EEP — Enterprise Edge Platform

**Location:** `services/eep/`  
**Runtime:** FastAPI + uvicorn, Python 3.11, asyncpg connection pool  
**Entry point:** `app/main.py` → `lifespan()` → `app = FastAPI(lifespan=lifespan)`

### 3.1 Startup Sequence (`lifespan`)

```python
async with engine.begin() as conn:
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ"))
    await conn.run_sync(ModelBase.metadata.create_all)   # idempotent DDL

ensure_bucket()                                          # MinIO bucket init
asyncio.create_task(_cleanup_deactivated_users())        # daily background task
await start_grpc_server()                                # gRPC on :50051 (before scheduler)
start_scheduler()                                        # APScheduler evaluate_schedules every 60 s
yield
stop_scheduler()
await stop_grpc_server(grace=5.0)
```

Order matters: gRPC must start before APScheduler because scheduler tasks call `registry.send_command()`.

### 3.2 Database Layer

**`app/core/database.py`**

```python
engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db() -> AsyncSession:   # FastAPI dependency
    async with AsyncSessionLocal() as session:
        try: yield session
        except: await session.rollback(); raise
```

`AsyncSessionLocal` is used directly (not via `session_scope()` — that function does not exist) for non-request DB access (scheduler, servicer, orchestrator). Callers are responsible for `await session.commit()`.

**`app/core/config.py`** — `pydantic_settings.BaseSettings`, env file `.env`, `extra="ignore"`. All 15 settings fields have safe defaults for local dev.

### 3.3 SQLAlchemy Models

All models use SQLAlchemy 2.x `Mapped[T] = mapped_column(...)` style. Base class: `app/models/base.py`.

| Model | Table | Notes |
|-------|-------|-------|
| `User` | `users` | `deactivated_at TIMESTAMPTZ` added at startup if absent |
| `Store` | `stores` | `status`, `timezone`, `operating_hours JSONB` |
| `StoreMember` | `store_members` | role: owner/manager/member |
| `PhysicalCamera` | `physical_cameras` | `cloud_stream_url` → RTSP URL for IEP1 |
| `StoreConfigVersion` | `store_config_versions` | status: draft/active/archived |
| `CameraConfig` | `camera_configs` | FK → `physical_cameras`, `store_config_versions` |
| `Calibration` | `calibrations` | `homography_matrix JSONB`, `is_current`, `method` |
| `Zone` | `zones` | `points JSONB` (polygon vertices) |
| `StoreSettings` | `store_settings` | `frame_sample_rate_fps INTEGER DEFAULT 5` |
| `CameraSchedule` | `camera_schedules` | `days_of_week INTEGER[]`, `start_time TIME`, `end_time TIME` |
| `AuditLog` | `audit_logs` | all write operations |

`CameraSchedule` validation (Pydantic schemas):
- `days_of_week`: values 0–6, no duplicates (`@field_validator`)
- `start_time < end_time` (`@model_validator(mode="after")`)
- `TriggerRequest.action`: must be `"start"` or `"stop"`

### 3.4 REST API Routes

All routes use `prefix="/api"` at registration. Store-scoped routes use `get_store_context` middleware for slug→store_id resolution and JWT validation.

**Auth** (`/api/auth/*`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | — | Create user account |
| POST | `/api/auth/login` | — | Returns `access_token` + `refresh_token` |
| POST | `/api/auth/refresh` | refresh JWT | Rotate tokens |
| POST | `/api/auth/logout` | JWT | Revoke refresh token |
| POST | `/api/auth/request-password-reset` | — | Send reset email |
| POST | `/api/auth/reset-password` | — | Consume reset token |

**Stores** (`/api/stores/*`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/stores` | JWT | Create store (owner role assigned) |
| GET | `/api/stores` | JWT | List user's stores |
| GET | `/api/store/{slug}` | store member | Get store detail |
| PATCH | `/api/store/{slug}` | owner/manager | Update store |
| DELETE | `/api/store/{slug}` | owner | Soft-delete store |

**Members, Invitations** (`/api/store/{slug}/members/*`)

CRUD for `StoreMember`. Invitation flow with email delivery via `aiosmtplib`.

**Config / Draft** (`/api/store/{slug}/draft/*`, `/api/store/{slug}/versions/*`)

Full configuration lifecycle: draft creation, physical camera CRUD, camera config CRUD, calibration upload (homography correspondences → computed H matrix stored in JSONB), zone CRUD, version activation with `countdown_sec`, version sync event tracking.

**Camera Schedules** (`/api/store/{slug}/schedules/*`)

| Method | Path | Auth | Status | Description |
|--------|------|------|--------|-------------|
| GET | `/api/store/{slug}/schedules` | member | 200 | List all schedules |
| POST | `/api/store/{slug}/schedules` | owner/manager | 201 | Create schedule; validates `camera_config_id` belongs to store |
| PATCH | `/api/store/{slug}/schedules/{id}` | owner/manager | 200 | Partial update |
| DELETE | `/api/store/{slug}/schedules/{id}` | owner/manager | 204 | Delete |
| POST | `/api/store/{slug}/schedules/{id}/trigger` | owner/manager | 202 | Manual start/stop; calls orchestrator + syncs scheduler state |

The trigger endpoint:
1. Calls `orchestrator.start_camera_workers()` or `stop_camera_workers()`
2. Calls `mark_running()` or `mark_stopped()` to keep `_running_cameras` in sync
3. Returns 202 — workers start asynchronously in Docker, 202 signals "instruction issued"

**Employees, Shifts** — full CRUD for `Employee`, `ShiftPattern`, `ShiftInstance` (not covered in this audit cycle).

**Audit** (`/api/store/{slug}/audit`) — append-only `AuditLog` read endpoint.

**Debug** (`/api/debug/agent/command`) — only registered when `DEBUG_MODE=true`.

```python
POST /api/debug/agent/command
Body: { store_id, camera_id, action: "start"|"stop", rtsp_url?, target_fps?, window_seconds? }
Response 202: { status: "sent", action, camera_id }
Response 404: No agent connected for store
```

Directly calls `registry.send_command()` to push a `ControlMessage` to the connected edge agent.

### 3.5 gRPC Server

**`app/grpc_server/server.py`**

```python
_server: grpc.aio.Server | None = None

async def start_grpc_server(port=50051):
    _server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServiceServicer(), _server)
    _server.add_insecure_port(f"[::]:{port}")
    await _server.start()

async def stop_grpc_server(grace=5.0):
    await _server.stop(grace=grace)
```

Uses `grpc.aio` (async). Not the sync gRPC server — that would block the FastAPI event loop.

**`app/grpc_server/registry.py`**

```python
_connections: dict[str, asyncio.Queue] = {}  # store_id → queue

async def register(store_id) -> asyncio.Queue    # replaces existing on reconnect
def deregister(store_id)
async def send_command(store_id, msg: ControlMessage) -> bool  # False if not connected
def connected_stores() -> list[str]
```

Module-level dict. Importable from anywhere in EEP. On agent reconnect, the old queue is replaced — the old writer task sees a dead stream and exits cleanly.

**`app/grpc_server/servicer.py`** — `AgentServiceServicer.Connect()`

Protocol:
1. First message **must** be `Heartbeat`. Any other type → `context.abort(INVALID_ARGUMENT)`.
2. `store_id` extracted from first heartbeat, registered in `registry`.
3. Two concurrent tasks: `_reader` (processes incoming `AgentMessage`), `_writer` (drains queue → `context.write(ControlMessage)`).
4. `asyncio.wait([reader_task, writer_task], return_when=FIRST_COMPLETED)` — whichever finishes first causes the other to be cancelled.
5. `finally` block: `registry.deregister()`, UPSERT `edge_agents.status = 'offline'`.

`_upsert_agent()` uses `ON CONFLICT (store_id)` UPSERT:

```sql
INSERT INTO edge_agents (store_id, status, last_heartbeat_at, agent_version, updated_at)
VALUES (:store_id::uuid, :status, :now, :version, :now)
ON CONFLICT (store_id) DO UPDATE SET
    status            = EXCLUDED.status,
    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
    agent_version     = COALESCE(EXCLUDED.agent_version, edge_agents.agent_version),
    updated_at        = EXCLUDED.updated_at
```

`agent_version` uses `COALESCE` — subsequent heartbeats where version is `None` (stop event) preserve the last-known version.

### 3.6 Camera Schedule Evaluator

**`app/core/scheduler.py`**

```python
scheduler = AsyncIOScheduler(timezone="UTC")

def start_scheduler():
    from app.tasks.camera_scheduler import evaluate_schedules  # lazy import avoids circular
    scheduler.add_job(evaluate_schedules, trigger="interval", seconds=60,
                      id="camera_schedule_evaluator", replace_existing=True, max_instances=1)
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown(wait=False)
```

`max_instances=1` prevents overlapping evaluations if a cycle takes >60 s.

**`app/tasks/camera_scheduler.py`**

```python
_running_cameras: set[tuple[str, str]] = set()  # (store_id, camera_config_id)

def mark_running(store_id, camera_config_id)   # called by trigger endpoint
def mark_stopped(store_id, camera_config_id)   # called by trigger endpoint
```

`evaluate_schedules()` flow:
1. Load all `is_active=true` schedules + store `timezone` via `_LOAD_SQL`
2. `now_utc.astimezone(ZoneInfo(store_timezone))` → per-store local time
3. `_should_run(row, now_local)`: `weekday() in days_of_week AND start_time <= current_time < end_time`
4. `if should_run and key not in _running_cameras` → `await _on_camera_start(row)` → `_running_cameras.add(key)`
5. `if not should_run and key in _running_cameras` → `await _on_camera_stop(row)` → `_running_cameras.discard(key)`

Errors in `_on_camera_start`/`_on_camera_stop` are caught and logged. One camera failure never blocks others. DB load failure skips the entire tick.

`_running_cameras` resets on EEP restart. This means a camera scheduled to run during an EEP restart will start again on the next 60 s tick rather than being double-started.

### 3.7 Orchestrator

**`app/core/orchestrator.py`**

`_load_camera_data()` query:

```sql
SELECT
    cc.id                                   AS camera_config_id,
    pc.id                                   AS physical_camera_id,
    pc.cloud_stream_url                     AS rtsp_url,
    COALESCE(ss.frame_sample_rate_fps, 5.0) AS target_fps
FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN physical_cameras pc       ON pc.id  = cc.physical_camera_id
LEFT JOIN store_settings ss    ON ss.store_id = scv.store_id
WHERE cc.id = :camera_config_id AND scv.store_id = :store_id
LIMIT 1
```

`start_camera_workers(store_id, camera_config_id)`:
1. Load camera data (returns early with warning if `None`)
2. Push `StartCamera` gRPC to edge agent via `registry.send_command()` (best-effort — logs warning if agent not connected, does not raise)
3. Call `iep2_docker.start_iep2(...)` via `loop.run_in_executor(None, ...)` (mandatory — always runs regardless of IEP1 status)

`stop_camera_workers(store_id, camera_config_id)`:
1. Load camera data
2. Push `StopCamera` gRPC (best-effort)
3. `iep2_docker.stop_iep2(...)` via executor (mandatory)

`window_seconds` is hardcoded to `60.0` in `StartCamera`. Must match IEP1 default and IEP2 batch window.

### 3.8 IEP2 Docker Manager

**`app/core/iep2_docker.py`**

```python
IEP2_IMAGE     = os.environ.get("IEP2_IMAGE",     "retailvision-iep2:latest")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "retail-edge_default")

def container_name(store_id, physical_camera_id) -> str:
    return f"iep2_{store_id}_{physical_camera_id}"

def start_iep2(store_id, physical_camera_id, camera_config_id,
               database_url, redis_url, s3_endpoint_url,
               s3_access_key, s3_secret_key, s3_bucket) -> None:
    # 1. Remove existing same-named container with force=True (handles crash/restart)
    # 2. containers.run(image, command=[...], environment={...},
    #                   network=DOCKER_NETWORK, detach=True,
    #                   restart_policy={"Name": "on-failure", "MaximumRetryCount": 3})

def stop_iep2(store_id, physical_camera_id) -> None:
    # container.stop(timeout=10); NotFound is silently ignored

def get_iep2_status(store_id, physical_camera_id) -> str:
    # "running" | "stopped"
```

All functions are **synchronous** (docker-py makes blocking network calls). Always called via `asyncio.get_running_loop().run_in_executor(None, fn, ...)`.

EEP's own `DATABASE_URL`, `REDIS_URL`, `S3_*` env vars are forwarded directly to IEP2 containers. No separate IEP2 config.

IEP2 container CLI:

```
python -m services.iep2_vision.main
  --store-id        {store_id}
  --camera-id       {physical_camera_id}
  --source          redis
  --camera-config-id {camera_config_id}
```

### 3.9 Generated gRPC Stubs (EEP)

**`app/grpc_generated/agent_pb2.py`** — protobuf message classes (serialized descriptor, do not edit)  
**`app/grpc_generated/agent_pb2_grpc.py`** — service stub + servicer base class

Import fix applied: `from app.grpc_generated import agent_pb2 as agent__pb2` (grpcio-tools generates a bare `import agent_pb2` which breaks inside a package).

Regeneration command (run from `retail-edge/`):
```bash
python -m grpc_tools.protoc \
  -I services/eep/proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  services/eep/proto/agent.proto
# Then reapply the import fix in agent_pb2_grpc.py
```

---

## 4. IEP1 — Ingestion Pipeline

**Location:** `services/iep1_ingestion/`  
**Runtime:** Python 3.11, synchronous (no asyncio), one process per camera  
**Entry point:** `python -m services.iep1_ingestion.app.main`  
**Dockerfile pattern:** `WORKDIR /workspace`, `mkdir -p services/iep1_ingestion`, `COPY app/ services/iep1_ingestion/app/`, `touch services/__init__.py`

### 4.1 CLI Arguments

```
--store-id   required  Store identifier
--camera-id  required  Camera identifier  
--rtsp       optional  RTSP stream URL (mutually exclusive with --video)
--video      optional  Video file path (for dev/test)
--fps        float     Target FPS (default: 5.0)
--window     float     Batch window seconds (default: 60.0)
```

Exactly one of `--rtsp` or `--video` must be provided. `argparse.error()` enforces mutual exclusion.

### 4.2 Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `S3_ENDPOINT_URL` | — | MinIO/S3 endpoint |
| `S3_ACCESS_KEY` | — | |
| `S3_SECRET_KEY` | — | |
| `S3_BUCKET` | `retailvision` | |
| `REDIS_URL` | `redis://localhost:6379/0` | |

### 4.3 `Iep1Settings` Dataclass

```python
@dataclass
class Iep1Settings:
    store_id:             str
    camera_id:            str
    rtsp_url:             str | None = None
    target_fps:           float = 5.0
    batch_window_seconds: float = 60.0
    s3_bucket:            str   = "retailvision"
    redis_url:            str   = "redis://localhost:6379/0"
```

### 4.4 Frame Sources (FrameSource Protocol)

Both sources implement: `frames() → Iterator[(capture_ts_ms, frame)]`, `is_available() → bool`, `release()`.

**`RtspSource`** — `cv2.VideoCapture(rtsp_url)`. Real-time, blocks on reads.

**`VideoFileSource`** — `cv2.VideoCapture(video_path)`. Key implementation details:
- `source_fps = cap.get(cv2.CAP_PROP_FPS)` — defaults to `target_fps` if unreadable
- `effective_fps = min(target_fps, source_fps)` — no upsampling
- Decimation: `n = max(1, round(source_fps / effective_fps))` — yield every n-th frame
- `capture_ts_ms = start_epoch_ms + int(frame_index * 1000 / source_fps)` — synthetic timestamps anchored to real wall clock

`source` is injected into `Iep1Runtime.__init__` — constructed in `main()` and passed in, not hardcoded.

### 4.5 `Iep1Runtime.run()`

```python
window_start_ms = now_ms()
batch_duration_ms = settings.batch_window_seconds * 1000

for capture_ts_ms, frame in source.frames():
    key = uploader.upload(capture_ts_ms, frame)       # JPEG → S3
    accumulator.add(capture_ts_ms, key)               # append to window
    flush_expired_batches()                           # delete S3 keys >300 s old

    if now_ms() - window_start_ms >= batch_duration_ms:
        _close_window(window_start_ms)                # publish manifest → Redis
        window_start_ms = now_ms()
```

`_close_window()` calls `publisher.publish(manifest)` which does `XADD stream:iep1:{camera_id}`.

`BATCH_TTL_SECONDS = 300` — S3 frames are deleted 300 s after their batch closes. `_pending_cleanup` is a `deque` of `(close_time_ms, [s3_keys])`.

On exit (`finally`): final window closed, all pending cleanup flushed, all remaining S3 keys deleted unconditionally, `source.release()` called.

### 4.6 `WindowAccumulator`

Tracks frames for the current batch window. `close()` produces a `Manifest` with `status`, `frame_count`, `expected_frames`, `gaps`, and `frames` list. If no frames were captured (camera offline), `status="offline"`.

### 4.7 `WindowPublisher`

```python
redis.xadd(f"stream:iep1:{camera_id}", {"manifest": json.dumps(manifest_dict)})
```

Uses sync `redis` client (not async). IEP1 is fully synchronous.

---

## 5. IEP2 — Vision Pipeline

**Location:** `services/iep2_vision/`  
**Runtime:** Python 3.11, asyncio throughout, one process per camera  
**Entry point:** `python -m services.iep2_vision.main` (or `python services/iep2_vision/main.py`)  
**Models loaded once** at `IEP2Runtime.__init__()` — YOLO (yolov8n.pt) and ReID (osnet_x1_0).

### 5.1 CLI Arguments

```
--store-id          required  Store UUID
--camera-id         required  Physical camera ID (text, used as camera_id in tracking_history)
--camera-config-id  optional  UUID of camera_configs row; enables floor projection
--source            video|redis  (default: video)
--video             required if --source video
--start-ms          int (default: 0)
```

### 5.2 `Iep2Settings` Dataclass

```python
@dataclass
class Iep2Settings:
    store_id:            str
    camera_id:           str
    database_url:        str
    camera_config_id:    str | None = None
    redis_url:           str        = "redis://localhost:6379/0"
    s3_endpoint_url:     str        = ""
    s3_access_key:       str        = ""
    s3_secret_key:       str        = ""
    s3_bucket:           str        = "retailvision"
    target_fps:          float      = 5.0
    live_stream_enabled: bool       = True
```

### 5.3 `PostgresPersistence`

**`persistence/postgres.py`**

```python
class PostgresPersistence:
    def __init__(self, database_url, store_id, camera_id):
        self._store_id = uuid.UUID(store_id)   # parsed once at init
        self._pool = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)

    async def insert_detection(self, local_id, timestamp_ms, bbox_confidence,
                               bbox_area, floor_x, floor_y, zone_id):
        await self._pool.execute(_INSERT_SQL, self._store_id, self._camera_id,
                                 local_id, timestamp_ms, floor_x, floor_y,
                                 zone_id, bbox_confidence, bbox_area)

    # async context manager: __aenter__ → connect(), __aexit__ → close()
```

`_INSERT_SQL` uses positional `$1…$9` parameters (asyncpg style). No ORM. No DDL — schema is created by EEP at startup via `schema.sql`.

### 5.4 `FloorProjector`

**`projection/projector.py`**

Loaded after DB pool opens, reuses the same asyncpg pool (no second connection).

```python
async def load(self, pool: asyncpg.Pool, camera_config_id: uuid.UUID):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_HOMOGRAPHY_SQL, camera_config_id)
        # Homography query: calibrations WHERE camera_config_id=$1
        #   AND is_current=true AND status IN ('ok','verified') AND method='homography'
        zone_rows = await conn.fetch(_ZONES_SQL, camera_config_id)
        # Zone query: zones JOIN store_config_versions JOIN camera_configs
        #   WHERE cc.id=$1 AND scv.status='active'
```

`project(x1, y1, x2, y2)` — pure numpy:

```python
px = (x1 + x2) / 2.0   # horizontal centre
py = float(y2)          # bottom of bbox (foot point)
src = np.array([px, py, 1.0], dtype=np.float64)
dst = self._H @ src
return float(dst[0] / dst[2]), float(dst[1] / dst[2])
```

`zone_of(floor_x, floor_y)` — shapely `Point.contains(polygon)` test, returns first matching zone UUID.

`_parse_homography()` handles both flat `(9,)` and `(3,3)` JSONB storage formats.

If no homography loaded: `project()` returns `None`, `floor_x/floor_y/zone_id` stored as `NULL`.

### 5.5 `RedisStreamFrameSource`

**`ingest/redis_source.py`**

```python
STREAM_PREFIX = "stream:iep1"
GROUP_NAME    = "iep2_workers"
BLOCK_MS      = 2000
READ_COUNT    = 10

class RedisStreamFrameSource:
    def __init__(self, camera_id, redis_url, s3_client):
        self._stream_name   = f"{STREAM_PREFIX}:{camera_id}"
        self._consumer_name = f"iep2_{camera_id}"
```

`_ensure_group()`: `XGROUP CREATE ... mkstream=True`, catches `BUSYGROUP` error silently.

`manifests()` async generator:
- **Phase A**: `XREADGROUP ID="0"` until empty → crash recovery
- **Phase B**: `XREADGROUP ID=">"` infinite loop → normal operation
- Yields `(message_id, manifest_dict)`

`ack(message_id)`: caller calls after full manifest processed and DB writes committed.

Manifest field decoded: `fields.get(b"manifest") or fields.get("manifest")` → `json.loads(raw)`.

### 5.6 Per-Frame Pipeline (`_run_frame_detections`)

```python
for track in enriched:
    if track["local_id"] is not None:
        x1, y1, x2, y2 = [int(c) for c in track["bbox"]]
        bbox_area = (x2 - x1) * (y2 - y1)
        local_id_uuid = uuid.UUID(int=track["local_id"])   # int → UUID conversion
        proj = projector.project(x1, y1, x2, y2)
        floor_x, floor_y = proj if proj else (None, None)
        zone_id = projector.zone_of(floor_x, floor_y) if proj else None
        await persistence.insert_detection(
            local_id=local_id_uuid, timestamp_ms=capture_ts_ms,
            bbox_confidence=float(track["confidence"]),
            bbox_area=bbox_area, floor_x=floor_x, floor_y=floor_y, zone_id=zone_id
        )
```

`LocalIdentityManager.process_frame()` returns `int` local_ids. `uuid.UUID(int=local_id)` converts deterministically (same int always → same UUID). Only tracks with `local_id is not None` (identity confirmed) are written to DB.

### 5.7 IEP1 Redis Pipeline (`_stream_from_iep1`)

```python
async for message_id, manifest in source.manifests():
    if manifest.get("status") == "offline":
        await source.ack(message_id)   # ACK and skip offline windows
        continue

    for frame_entry in manifest.get("frames", []):
        capture_ts_ms, s3_key = int(frame_entry[0]), frame_entry[1]
        frame = _fetch_s3_frame(s3_client, s3_bucket, s3_key)
        if frame is None: continue
        # detect → track → identify → project → insert
        ...

    await source.ack(message_id)   # ACK after all frames written to DB
```

XACK is manifest-scoped, not frame-scoped. A crash mid-manifest replays the entire manifest on restart (Phase A recovery).

### 5.8 S3 Frame Fetch

```python
def _fetch_s3_frame(s3_client, bucket, key) -> np.ndarray | None:
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data = resp["Body"].read()
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)  # None on failure
```

`boto3` S3 client is sync (blocking). Acceptable for single-camera process — one S3 call per frame sequentially.

---

## 6. Edge Agent

**Location:** `services/edge_agent/`  
**Runtime:** Python 3.11, asyncio, grpc.aio client, no HTTP server  
**Entry point:** `python -m services.edge_agent.app.main`  
**Dockerfile pattern:** same as IEP1 (`WORKDIR /workspace`, `mkdir -p services/edge_agent`, etc.)

### 6.1 Configuration (env vars only)

| Var | Required | Default | Description |
|-----|----------|---------|-------------|
| `EEP_GRPC_URL` | yes | — | e.g. `eep:50051` or `localhost:50051` |
| `STORE_ID` | yes | — | Store UUID this agent represents |
| `AGENT_VERSION` | no | `0.1.0` | Reported in heartbeats |
| `IEP1_IMAGE` | no | `retailvision-iep1:latest` | Docker image for IEP1 containers |
| `DOCKER_NETWORK` | no | `retail-edge_default` | Compose network name; verify with `docker network ls` |

Missing `EEP_GRPC_URL` or `STORE_ID` → `sys.exit(1)`.

### 6.2 Reconnect Loop (`run_agent`)

```python
backoff = 1
while True:
    try:
        await _connect(grpc_url, store_id, agent_version)
        backoff = 1   # reset on clean disconnect
    except Exception as exc:
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
```

Backoff: 1s → 2s → 4s … → 60s cap. Never retries faster than 1 s.

### 6.3 `_connect`

```python
async with grpc.aio.insecure_channel(grpc_url) as channel:
    stub = AgentServiceStub(channel)
    hb_task = asyncio.create_task(_heartbeat_loop(store_id, agent_version))
    try:
        async for ctrl_msg in stub.Connect(_request_generator()):
            await _handle_control(ctrl_msg)
    finally:
        hb_task.cancel(); await hb_task  # cancel+await on disconnect
```

`_request_generator()` is an async generator that `await _outgoing.get()` indefinitely. `_outgoing` is module-level — not recreated on reconnect. Any queued commands survive a disconnect/reconnect cycle.

### 6.4 Heartbeat Loop (`_heartbeat_loop`)

```python
while True:
    await _outgoing.put(AgentMessage(heartbeat=Heartbeat(
        store_id=store_id, agent_version=agent_version,
        timestamp_ms=int(time.time() * 1000)
    )))
    # Per-camera status reports
    for camera_id, cam_store_id in list(_tracked_cameras.items()):
        status = docker_manager.get_status(cam_store_id, camera_id)
        await _outgoing.put(AgentMessage(camera_status=CameraStatusReport(
            camera_id=camera_id, container_status=status,
            timestamp_ms=int(time.time() * 1000)
        )))
    await asyncio.sleep(30)
```

First heartbeat is put **immediately** (no initial sleep) — EEP's servicer requires Heartbeat as the first message. Subsequent heartbeats every 30 s, each followed by one `CameraStatusReport` per tracked camera.

### 6.5 Control Message Handler (`_handle_control`)

```python
loop = asyncio.get_running_loop()

if ctrl_msg.HasField("start_camera"):
    await loop.run_in_executor(None, docker_manager.start_iep1, cmd, IEP1_IMAGE, DOCKER_NETWORK)
    _tracked_cameras[cmd.camera_id] = cmd.store_id

elif ctrl_msg.HasField("stop_camera"):
    await loop.run_in_executor(None, docker_manager.stop_iep1, cmd.store_id, cmd.camera_id)
    _tracked_cameras.pop(cmd.camera_id, None)
```

`_tracked_cameras: dict[str, str]` — camera_id → store_id. Module-level. Survives reconnects.

### 6.6 `docker_manager.py`

```python
def container_name(store_id, camera_id) -> str:
    return f"iep1_{store_id}_{camera_id}"

def start_iep1(cmd, image, network):
    # Remove existing container force=True (crash recovery)
    # containers.run(image, command=[...], environment={...},
    #                network=network, detach=True,
    #                restart_policy={"Name": "on-failure", "MaximumRetryCount": 3})

def stop_iep1(store_id, camera_id):
    # container.stop(timeout=10); NotFound → log, no raise

def get_status(store_id, camera_id) -> "running" | "stopped":
    # container.status == "running" → "running", else → "stopped"
    # NotFound → "stopped"
```

IEP1 container command:
```
python -m services.iep1_ingestion.app.main
  --store-id  {store_id}
  --camera-id {camera_id}
  --rtsp      {rtsp_url}
  --fps       {target_fps}
  --window    {window_seconds}
```

All sync. Always called via `run_in_executor`.

### 6.7 Generated gRPC Stubs (Edge Agent)

**`app/grpc_generated/agent_pb2.py`** + **`agent_pb2_grpc.py`** — generated from `proto/agent.proto` (byte-for-byte identical to EEP's proto).

Import fix: `from services.edge_agent.app.grpc_generated import agent_pb2 as agent__pb2`.

Note: EEP's fix uses `from app.grpc_generated import agent_pb2` (different base package because EEP's Dockerfile puts code at `/app/`). Edge Agent uses `from services.edge_agent.app.grpc_generated import agent_pb2` because the Dockerfile mirrors the `services.edge_agent.*` module path under `/workspace/`.

---

## 7. gRPC Protocol

**Proto:** `services/eep/proto/agent.proto` (canonical) ↔ `services/edge_agent/proto/agent.proto` (copy, must be byte-for-byte identical)  
**Package:** `retailvision.agent.v1`  
**Transport:** insecure (no TLS in current implementation)  
**Versions:** `grpcio==1.64.0`, `grpcio-tools==1.64.0` (must match exactly)

### 7.1 Service Definition

```protobuf
service AgentService {
  rpc Connect(stream AgentMessage) returns (stream ControlMessage);
}
```

Single bidirectional streaming RPC. Edge agent dials out; stream stays open for agent lifetime.

### 7.2 Message Hierarchy

**Edge → Cloud (`AgentMessage`):**

```protobuf
message AgentMessage {
  oneof payload {
    Heartbeat          heartbeat     = 1;
    CameraStatusReport camera_status = 2;
  }
}
message Heartbeat {
  string store_id;       // identifies which store's agent this is
  string agent_version;
  int64  timestamp_ms;
}
message CameraStatusReport {
  string camera_id;        // physical_camera UUID as string
  string container_status; // "running" | "stopped" | "error"
  int64  timestamp_ms;
}
```

**Cloud → Edge (`ControlMessage`):**

```protobuf
message ControlMessage {
  oneof payload {
    StartCamera start_camera = 1;
    StopCamera  stop_camera  = 2;
  }
}
message StartCamera {
  string   camera_id;       // physical_camera UUID
  string   store_id;
  string   rtsp_url;
  float    target_fps;
  float    window_seconds;  // must be 60.0 — matches IEP2 batch window
  S3Config s3_config;
  string   redis_url;
}
message StopCamera {
  string camera_id;
  string store_id;
}
message S3Config {
  string endpoint_url;
  string access_key;
  string secret_key;
  string bucket;
}
```

### 7.3 Protocol Invariants

- First `AgentMessage` must be `Heartbeat`. Enforced server-side with `INVALID_ARGUMENT` abort.
- `store_id` in proto messages is a `string` (UUID formatted). Cast to `::uuid` only in SQL.
- `window_seconds = 60.0` is hardcoded in orchestrator. Changing it requires updating IEP1 `--window`, IEP2 batch window, and the proto default.
- `camera_id` in `StartCamera` = `physical_camera.id` UUID (not `camera_config.id`). These are different UUIDs.

---

## 8. Cross-Service Data Flows

### 8.1 Schedule → Workers Start (normal path)

```
[SERVER] APScheduler fires (every 60 s)
  → evaluate_schedules()
    → _LOAD_SQL: SELECT camera_schedules JOIN stores WHERE is_active=true AND status='active'
    → per-schedule: _should_run(row, now_local_tz)
    → _on_camera_start(row) if should_run and not already running
      → orchestrator.start_camera_workers(store_id, camera_config_id)
          → _load_camera_data: JOIN camera_configs → physical_cameras → store_settings

          ── IEP1 path (best-effort) ──────────────────────────────────────
          → registry.send_command(store_id, StartCamera{...})
            → asyncio.Queue.put() → _writer task → context.write()
              ── gRPC stream ──────────────────────────────────────────────
              [EDGE] → Edge Agent _handle_control()
                → run_in_executor(docker_manager.start_iep1, cmd, IMAGE, NETWORK)
                  → edge docker.containers.run("iep1_...", detach=True)
                    → IEP1: frames → MinIO S3 (server) → Redis XADD (server)

          ── IEP2 path (mandatory) ────────────────────────────────────────
          [SERVER] → run_in_executor(iep2_docker.start_iep2, ...)
            → server docker.containers.run("iep2_...", detach=True)
              → IEP2: XREADGROUP (Redis on server) → S3 fetch → YOLO
                    → track → project → INSERT tracking_history (server DB)
```

### 8.2 Manual Trigger Path

```
POST /api/store/{slug}/schedules/{id}/trigger {action: "start"}
  → require_owner_or_manager(ctx)
  → _get_schedule_or_404()
  → orchestrator.start_camera_workers(store_id_str, config_id_str)
    → (same as 8.1 from orchestrator onward)
  → mark_running(store_id_str, config_id_str)
    → _running_cameras.add((store_id_str, config_id_str))
  → 202 {status: "accepted", action: "start", schedule_id, camera_config_id}
```

`mark_running()` is critical — prevents scheduler double-starting a manually triggered camera on the next 60 s cycle.

### 8.3 IEP1 → IEP2 Frame Delivery

```
[EDGE] IEP1 (camera loop, runs on edge device):
  frame captured → cv2.imencode JPEG → S3.put_object(Key=frames/{cam}/{batch}/{ts}.jpg)
                                        ↑ MinIO S3 endpoint on server (S3_ENDPOINT_URL)
  accumulator.add(ts_ms, s3_key)
  if window elapsed:
    manifest = {frames: [[ts, key], ...], status, batch_number, ...}
    redis.XADD stream:iep1:{camera_id} {manifest: json(manifest)}
              ↑ Redis on server (REDIS_URL)

[SERVER] IEP2 (redis consumer loop, runs on server alongside EEP):
  XREADGROUP iep2_workers iep2_{cam} stream:iep1:{cam} > COUNT 10 BLOCK 2000
  for each message:
    manifest = json.loads(fields["manifest"])
    if offline: XACK; continue
    for [ts, key] in manifest.frames:
      frame = s3.get_object(Bucket, Key) → np.frombuffer → cv2.imdecode
      detections = yolo.detect(frame)
      tracks = bytetrack.update(detections)
      enriched = identity_manager.process_frame(frame, tracks)
      for track with local_id:
        floor_x, floor_y = homography @ foot_point / w
        zone_id = shapely.contains(floor_x, floor_y)
        asyncpg.execute INSERT INTO tracking_history
    XACK stream:iep1:{cam} iep2_workers message_id
```

### 8.4 Agent Heartbeat → DB

```
Edge Agent (every 30 s):
  _outgoing.put(AgentMessage{heartbeat: {store_id, agent_version, ts}})
  for cam in _tracked_cameras:
    status = docker_manager.get_status(cam)   # sync
    _outgoing.put(AgentMessage{camera_status: {cam, status, ts}})

_request_generator → stub.Connect → gRPC stream → EEP servicer._reader
  Heartbeat → _upsert_agent(store_id, version, "online")
    → asyncpg INSERT INTO edge_agents ON CONFLICT (store_id) DO UPDATE

On disconnect:
  servicer.Connect finally block → _upsert_agent(store_id, status="offline")
```

---

## 9. Environment Variables Reference

### EEP (`services/eep/`)

| Var | Default | Description |
|-----|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5432/retailvision` | SQLAlchemy async URL |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | MinIO |
| `S3_PUBLIC_URL` | — | Public-facing S3 URL for signed URLs |
| `S3_ACCESS_KEY` | `retailvision` | |
| `S3_SECRET_KEY` | `retailvision_dev` | |
| `S3_BUCKET` | `retailvision` | |
| `JWT_SECRET` | `dev-secret-change-in-production` | **Change in production** |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | — | Email delivery |
| `DEBUG_MODE` | `true` (compose default) | Enables `/api/debug/*` routes |
| `IEP2_IMAGE` | `retailvision-iep2:latest` | Docker image for IEP2 |
| `DOCKER_NETWORK` | `retail-edge_default` | Network for IEP2 containers |

### IEP1 (`services/iep1_ingestion/`)

| Var | Default | Description |
|-----|---------|-------------|
| `S3_ENDPOINT_URL/ACCESS_KEY/SECRET_KEY/BUCKET` | — | Frame upload |
| `REDIS_URL` | `redis://localhost:6379/0` | Manifest publish |

### IEP2 (`services/iep2_vision/`)

| Var | Required | Description |
|-----|----------|-------------|
| `DATABASE_URL` | yes | `postgresql://...` (no `+asyncpg` prefix — direct asyncpg) |
| `REDIS_URL` | — | Consumer group source |
| `S3_ENDPOINT_URL/ACCESS_KEY/SECRET_KEY/BUCKET` | — | Frame download |
| `LIVE_STREAM_ENABLED` | — | Enable LivePublisher (Redis pub/sub for UI) |

### Edge Agent (`services/edge_agent/`)

| Var | Required | Default | Description |
|-----|----------|---------|-------------|
| `EEP_GRPC_URL` | yes | — | `host:50051` |
| `STORE_ID` | yes | — | Store UUID |
| `AGENT_VERSION` | — | `0.1.0` | Reported in heartbeats |
| `IEP1_IMAGE` | — | `retailvision-iep1:latest` | |
| `DOCKER_NETWORK` | — | `retail-edge_default` | Verify: `docker network ls \| grep retail` |

---

## 10. Dependency Versions

### EEP (`services/eep/requirements.txt`)

```
fastapi==0.115.0
uvicorn[standard]==0.30.1
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
redis[asyncio]==5.0.4
boto3==1.34.69
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==3.2.2
python-multipart==0.0.9
pydantic-settings==2.2.1
email-validator==2.1.1
httpx==0.27.0
aiosmtplib==3.0.1
shapely==2.0.4
opencv-python-headless==4.9.0.80
numpy==1.26.4
apscheduler==3.10.4
grpcio==1.64.0
grpcio-tools==1.64.0
docker==7.1.0
```

### IEP1 (`services/iep1_ingestion/requirements.txt`)

```
opencv-python-headless==4.9.0.80
boto3==1.34.0
redis==5.0.1
python-dotenv==1.0.1
numpy==1.26.4
```

### IEP2 (`services/iep2_vision/requirements.txt`)

```
opencv-python-headless
ultralytics           # YOLOv8
supervision==0.22.0
boxmot>=10.0.0        # ByteTrack
asyncpg==0.29.0
shapely==2.0.4
python-dotenv==1.0.1
redis==5.0.1
boto3==1.34.0
fastapi, uvicorn[standard], numpy, Pillow
```

### Edge Agent (`services/edge_agent/requirements.txt`)

```
grpcio==1.64.0
grpcio-tools==1.64.0
docker==7.1.0
```

### Test (`tests/e2e/`)

```
pytest
pytest-asyncio==0.23.6
asyncpg
redis[asyncio]
boto3
```

`pyproject.toml`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`.

---

## 11. Known Gaps & Next Steps

### In-scope gaps (not yet implemented)

| Gap | Location | Impact |
|-----|----------|--------|
| `_running_cameras` resets on EEP restart | `camera_scheduler.py` | Cameras scheduled to be running at restart time will not start until the next 60 s tick. For most schedules this is acceptable. Fix: query `edge_agents` + Docker on startup to rebuild state. |
| Agent reconnect doesn't replay pending queue | `agent.py` | `_outgoing` is module-level and survives reconnect, but commands queued before disconnect are replayed in FIFO order — correct behaviour. However if the EEP process restarts, any buffered commands are lost. Fix: persist commands to Redis before queuing. |
| `CameraStatusReport` received by EEP but not acted on | `servicer.py` `_reader` | Camera status is logged only. Phase 7 comment says "update container state tracking here". The `_running_cameras` set is in Edge Agent, not EEP — EEP has no container-level state tracking beyond the gRPC stream liveness. |
| `edge_agents` table not in SQLAlchemy models | `models/__init__.py` | `edge_agents` is created via `schema.sql` and written via raw SQL in `servicer.py`. It is not mapped as a SQLAlchemy ORM model. This is intentional — the table is only written by the servicer and read by `schema.sql` introspection. Add a model if query composition via ORM is needed. |
| `grpcio` not in EEP requirements | `requirements.txt` | `grpcio-tools==1.64.0` is present and depends on `grpcio==1.64.0`, so it's installed transitively. Explicit pin `grpcio==1.64.0` should be added for clarity. |
| No TLS on gRPC | `server.py` | `add_insecure_port` — acceptable for dev/LAN. Production needs `add_secure_port` with SSL credentials. |
| No authentication on gRPC | `servicer.py` | Any process that knows EEP's address and port can connect as an agent with any `store_id`. Production needs mutual TLS or a shared secret in metadata. |
| DEBUG_MODE defaults to `true` in compose | `docker-compose.yml` | The debug endpoint has no auth. Must be `false` or removed entirely in production. |
| `IEP2_IMAGE` tag `latest` | `docker-compose.yml` | `latest` is mutable. Pin to a digest or semver tag for reproducible deployments. |
| Window seconds mismatch risk | `orchestrator.py` | `window_seconds=60.0` is hardcoded. IEP1's default `--window 60.0` and IEP2's 60 s batch window must all match. No runtime validation. |

### Out-of-scope (future phases)

- IEP3: Reconciliation — cross-camera identity merging
- IEP4: Alerts — zone occupancy thresholds, dwell time alerts
- IEP5: Analytics — aggregated heatmaps, path analysis
- IEP6: Embedded agent — Jetson/RPi optimised inference
- Production hardening: TLS, gRPC auth, K8s deployment, observability (Prometheus metrics from EEP, IEP1, IEP2)
