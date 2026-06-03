# RetailVision AI

An intelligent retail analytics platform that uses multi-camera computer vision to track customer movement, measure zone occupancy, and generate actionable insights for store managers.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SERVER HOST  (Docker Compose / cloud)                                  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  React Frontend  :3000  (Vite · React Router · Konva · Zustand)  │  │
│  └─────────────────────────────┬─────────────────────────────────────┘  │
│                                │ HTTP REST                              │
│  ┌─────────────────────────────▼─────────────────────────────────────┐  │
│  │  EEP  :8000 (REST) + :50051 (gRPC)                                │  │
│  │  FastAPI · SQLAlchemy asyncpg · APScheduler · grpc.aio            │  │
│  │  REST API · gRPC server · evaluate_schedules() every 60 s         │  │
│  │  Orchestrator → starts IEP2 via local Docker socket               │  │
│  └────────┬─────────────────────────────────────────────────────────┘  │
│            │ /var/run/docker.sock                                       │
│  ┌─────────▼───────────────────────────────────────────────────────┐   │
│  │  iep2_{store}_{cam}   IEP2 Vision                               │   │
│  │  XREADGROUP iep2_workers → S3 fetch → YOLOv8 → ByteTrack        │   │
│  │  → LocalIdentityManager (ReID) → FloorProjector (homography)    │   │
│  │  → INSERT tracking_history                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  PostgreSQL :5432    Redis :6379    MinIO :9000/:9001                   │
│                                                                         │
│  IEP3 Reconciliation · IEP4 Alerts · IEP5 Analytics · IEP6 AI Agent   │
│  (skeleton services — not yet implemented)                              │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │ gRPC bidirectional stream
                            │ (edge dials out to :50051, stream stays open)
                            │ IEP1 pushes frames → MinIO S3 (reachable from server)
                            │ IEP1 publishes manifests → Redis (reachable from server)
┌───────────────────────────▼─────────────────────────────────────────────┐
│  EDGE DEVICE                                                            │
│                                                                         │
│  Edge Agent  (Python daemon, no HTTP server)                            │
│    grpc.aio client · 30 s heartbeat · exponential-backoff reconnect     │
│    _handle_control() → docker_manager.start/stop_iep1()                 │
│            │ /var/run/docker.sock (edge host)                           │
│  ┌─────────▼───────────────────────────────────────────────────────┐   │
│  │  iep1_{store}_{cam}   IEP1 Ingestion                            │   │
│  │  Camera (RTSP or video file) → JPEG frames → MinIO S3           │   │
│  │  60 s window → manifest → Redis XADD stream:iep1:{camera_id}    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, React Router v6, Konva.js, Zustand, Tailwind CSS |
| API Gateway (EEP) | FastAPI 0.115, SQLAlchemy 2 async, Pydantic v2, APScheduler 3.10 |
| Edge-Cloud Comms | gRPC (grpcio 1.64, bidirectional streaming) |
| Computer Vision | YOLOv8 (Ultralytics), ByteTrack (boxmot), OpenCV |
| Floor Projection | NumPy homography, Shapely polygons |
| Database | PostgreSQL 15, asyncpg 0.29 |
| Cache / Streams | Redis 7 (XREADGROUP consumer groups) |
| Object Storage | MinIO (S3-compatible), boto3 |
| Container Control | docker-py 7.1 (EEP starts IEP2; Edge Agent starts IEP1) |
| Containerisation | Docker, Docker Compose |

---

## Project Structure

```
retail-edge/
├── docker-compose.yml              # All services: infra + EEP + IEPs + edge_agent
├── pyproject.toml                  # pytest config (asyncio_mode=auto)
├── codebase_audit.md               # Full technical spec for all services
├── services/
│   ├── eep/                        # Enterprise Endpoint Processor (fully implemented)
│   │   ├── proto/agent.proto       # gRPC contract (canonical)
│   │   └── app/
│   │       ├── api/routers/        # auth, stores, config, schedules, debug, …
│   │       ├── core/               # database, config, scheduler, orchestrator, iep2_docker
│   │       ├── grpc_server/        # registry, servicer, server (grpc.aio)
│   │       ├── grpc_generated/     # agent_pb2.py, agent_pb2_grpc.py (committed)
│   │       ├── models/             # SQLAlchemy ORM (Mapped[] style) — incl. CameraRuntimeSession
│   │       ├── schemas/            # Pydantic v2 request/response schemas
│   │       └── tasks/              # camera_scheduler.py (APScheduler job + pending_activation)
│   ├── iep1_ingestion/             # Ingestion worker (fully implemented)
│   │   └── app/
│   │       ├── source/             # RtspSource, VideoFileSource
│   │       ├── uploader.py         # S3Uploader
│   │       ├── window.py           # WindowAccumulator
│   │       ├── publisher.py        # WindowPublisher (Redis XADD)
│   │       ├── runtime.py          # Iep1Runtime
│   │       └── main.py             # CLI entry (--rtsp or --video)
│   ├── iep2_vision/                # Vision worker (fully implemented)
│   │   ├── detector/               # YOLOv8 wrapper
│   │   ├── tracker/                # ByteTrack wrapper
│   │   ├── reid/                   # ReID model (osnet_x1_0)
│   │   ├── identity/               # LocalIdentityManager
│   │   ├── persistence/            # PostgresPersistence (asyncpg)
│   │   ├── projection/             # FloorProjector (homography + shapely)
│   │   ├── ingest/                 # RedisStreamFrameSource (XREADGROUP)
│   │   ├── app/
│   │   │   └── main.py             # FastAPI dev server: /upload, /ws, /clear-tmp (dev only, not in Compose)
│   │   ├── runtime.py              # IEP2Runtime (asynccontextmanager)
│   │   └── main.py                 # CLI entry (--source video|redis)
│   ├── edge_agent/                 # Edge Agent daemon (fully implemented)
│   │   ├── proto/agent.proto       # Copy of EEP proto (must stay in sync)
│   │   └── app/
│   │       ├── grpc_generated/     # agent_pb2.py, agent_pb2_grpc.py (committed)
│   │       ├── agent.py            # run_agent, heartbeat loop, control handler
│   │       ├── docker_manager.py   # start/stop/status IEP1 containers
│   │       └── main.py             # Reads EEP_GRPC_URL, STORE_ID from env
│   ├── iep3_reconciliation/        # Skeleton — not yet implemented
│   ├── iep4_alerts/                # Skeleton — not yet implemented
│   ├── iep5_analytics/             # Skeleton — not yet implemented
│   └── iep6_agent/                 # Skeleton — not yet implemented
├── tests/
│   ├── unit/                       # Existing unit tests
│   └── e2e/
│       └── test_full_pipeline.py   # End-to-end integration test (Phase 8)
└── frontend/                       # React application
```

---

## Prerequisites

- **Docker Desktop** (includes Docker Compose v2) — required for everything  
  Download: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- **Git**

No local Python or Node.js install is required. All services run inside Docker.

> **Docker socket access (Linux only):** EEP needs to manage IEP2 containers via the Docker socket. On Linux, add your user to the `docker` group: `sudo usermod -aG docker $USER`, then log out and back in.

---

## Quick Start (Full Stack)

### 1. Clone and configure

```bash
git clone <repo-url>
cd retail-edge
```

Copy the environment file. The defaults work out of the box for local development — no edits needed.

**macOS / Linux:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

### 2. Build images

```bash
docker compose build
```

The first build takes several minutes (YOLOv8, OpenCV, grpcio).

### 3. Start the full stack

```bash
docker compose up -d postgres redis minio eep
```

Wait for all services to be healthy:

```bash
docker compose ps
```

EEP is ready when you see it running. First startup automatically:
- Runs schema migrations (creates all tables)
- Creates the MinIO `retailvision` bucket

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

Interactive API docs: **http://localhost:8000/docs**

---

## Running the Full Pipeline (Scheduled or Manual)

The pipeline activates cameras through two paths: a time-based schedule, or a manual trigger from the API.

### What "starting a camera" means

1. EEP pushes a `StartCamera` gRPC message to the Edge Agent → Edge Agent starts an **IEP1** container **on the edge device** (reads RTSP, uploads frames to MinIO S3, publishes manifests to Redis).
2. EEP starts an **IEP2** container **on the server host** via its local Docker socket (reads Redis manifests, runs YOLO+ByteTrack+ReID, writes `tracking_history` to PostgreSQL).

### Step 1 — Start infrastructure and EEP

```bash
docker compose up -d postgres redis minio eep
```

### Step 2 — Start the Edge Agent

In production the Edge Agent runs on the physical edge device and connects to EEP over the network. For local development it runs on the same machine using the `edge` Docker Compose profile:

```bash
docker compose --profile edge up -d edge_agent
```

The `edge` profile is intentionally excluded from the default `docker compose up` so the edge agent does not start automatically as part of the server stack.

Verify it connected:

```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT store_id, status, last_heartbeat_at FROM edge_agents;"
```

Expected: one row with `status = online`.

### Step 3 — Create a store and schedule via the API

Use the frontend onboarding wizard (Steps 1–9) or the API directly. See **http://localhost:8000/docs**.

### Step 4 — Trigger a camera manually (debug endpoint)

With `DEBUG_MODE=true` (the default in `docker-compose.yml`), a debug endpoint lets you push commands without waiting for a schedule:

```bash
docker compose exec eep curl -s -X POST http://localhost:8000/api/debug/agent/command \
  -H "Content-Type: application/json" \
  -d '{"store_id":"<store_uuid>","camera_id":"<physical_camera_uuid>","action":"start","rtsp_url":"rtsp://test/stream"}'
```

Or from your host machine:

```bash
curl -s -X POST http://localhost:8000/api/debug/agent/command \
  -H "Content-Type: application/json" \
  -d '{"store_id":"<store_uuid>","camera_id":"<physical_camera_uuid>","action":"start","rtsp_url":"rtsp://test/stream"}'
```

### Step 5 — Verify both containers started

```bash
docker ps --filter "name=iep1_" --format "table {{.Names}}\t{{.Status}}"
docker ps --filter "name=iep2_" --format "table {{.Names}}\t{{.Status}}"
```

Expected: one `iep1_*` container and one `iep2_*` container both Running.

### Step 6 — Check tracking rows

After 60+ seconds (one batch window):

```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT camera_id, COUNT(*), MIN(floor_x IS NOT NULL) FROM tracking_history GROUP BY camera_id;"
```

---

## Camera Schedules

Schedules automate the start/stop cycle. The EEP scheduler fires every 60 seconds and evaluates all active schedules against the store's local timezone.

### Create a schedule (API)

```bash
curl -s -X POST http://localhost:8000/api/store/<slug>/schedules \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_config_id": "<config_uuid>",
    "days_of_week": [0,1,2,3,4],
    "start_time": "09:00:00",
    "end_time": "21:00:00",
    "is_active": true
  }'
```

`days_of_week` values: `0` = Monday … `6` = Sunday (Python `weekday()` convention).

### Manual trigger via schedule endpoint

```bash
curl -s -X POST http://localhost:8000/api/store/<slug>/schedules/<schedule_id>/trigger \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'
```

Returns `202 Accepted` — workers start asynchronously in Docker.

---

## Version Activation

`StoreConfigVersion` follows a four-state lifecycle:

```
draft → pending_activation → active → archived
```

| State | Meaning |
|---|---|
| `draft` | Being edited — not deployed |
| `pending_activation` | Scheduled for future activation (`activate_at` is set) |
| `active` | Currently deployed — cameras run against this version |
| `archived` | Superseded — kept for history |

### Activate a draft version (API)

```bash
curl -s -X POST http://localhost:8000/api/store/<slug>/versions/draft/activate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"mode": "immediate"}'
```

**Immediate activation** (`mode: "immediate"`): stops cameras running on the old version, atomically archives it and activates the new one, restarts cameras with the new config. Returns `status: "activating"` with `cameras_restarted`.

**Scheduled activation** (`mode: "scheduled"`): archives the old version immediately, sets the draft to `pending_activation` with the given timestamp.

```bash
  -d '{"mode": "scheduled", "activate_at": "2026-06-04T09:00:00Z"}'
```

Returns `status: "scheduled"`. The EEP scheduler fires the activation automatically when `activate_at` passes (checked every 60 seconds). The `activate_at` timestamp must be in the future.

### Crash recovery on EEP restart

On startup, EEP queries `camera_runtime_sessions` for any sessions with `stopped_at IS NULL` — these represent cameras whose IEP2 container died while EEP was down. EEP attempts to restart IEP2 for each and re-adopts the existing session row. If restart fails the session is closed with `stop_reason = 'crash'` so history stays complete.

---

## Monitoring & Logs

### Service logs

```bash
docker compose logs -f eep            # EEP + gRPC server + scheduler
docker compose logs -f edge_agent     # heartbeats + container events
docker compose logs -f iep1_ingestion # frame upload + batch windows
docker compose logs -f iep2_vision    # detections + DB writes
```

### Verify edge agent connection

```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT store_id, status, last_heartbeat_at, agent_version FROM edge_agents;"
```

### Check Redis consumer group state

```bash
# List pending messages (should be 0 after IEP2 processes them)
docker compose exec redis redis-cli XPENDING stream:iep1:<camera_id> iep2_workers

# Count messages in stream
docker compose exec redis redis-cli XLEN stream:iep1:<camera_id>
```

### Check frames in MinIO

```bash
docker compose exec minio mc ls local/retailvision/frames/<camera_id>/
```

Or open the MinIO console: **http://localhost:9001** (user: `retailvision`, password: `retailvision_dev`).

### Check tracking data

```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT local_id, timestamp_ms, floor_x, floor_y, zone_id, bbox_confidence \
      FROM tracking_history \
      WHERE camera_id = '<camera_id>' \
      ORDER BY timestamp_ms DESC LIMIT 10;"
```

---

## Running Tests

All tests run inside Docker. No local Python environment is required.

### Unit tests

```bash
docker compose run --rm eep pytest tests/unit/ -v
```

### End-to-end integration test (Phase 8)

The e2e test verifies the complete pipeline: schedule trigger → IEP1 → Redis → IEP2 → `tracking_history`. It requires the full stack to be running and a camera to have processed at least 60 seconds of video.

**Prerequisites:**
- `docker compose up -d postgres redis minio eep` — all healthy
- Edge Agent running and status = online in `edge_agents`
- A camera triggered (see Running the Full Pipeline above)
- At least 60 seconds elapsed since trigger

**Run the test:**

```bash
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://retailvision:retailvision_dev@postgres:5432/retailvision \
  -e REDIS_URL=redis://redis:6379/0 \
  -e S3_ENDPOINT_URL=http://minio:9000 \
  -e S3_ACCESS_KEY=retailvision \
  -e S3_SECRET_KEY=retailvision_dev \
  -e S3_BUCKET=retailvision \
  -e E2E_CAMERA_ID=<physical_camera_uuid> \
  -e E2E_STORE_ID=<store_uuid> \
  eep pytest tests/e2e/test_full_pipeline.py -v
```

> `E2E_CAMERA_ID` is `physical_cameras.id` — **not** `camera_configs.id`. These are different UUIDs.

**Expected output:**

```
tests/e2e/test_full_pipeline.py::test_rows_exist              PASSED
tests/e2e/test_full_pipeline.py::test_local_id_is_uuid        PASSED
tests/e2e/test_full_pipeline.py::test_store_id_matches        PASSED
tests/e2e/test_full_pipeline.py::test_timestamp_ms_populated  PASSED
tests/e2e/test_full_pipeline.py::test_floor_coords_populated  PASSED
tests/e2e/test_full_pipeline.py::test_bbox_area_positive      PASSED
tests/e2e/test_full_pipeline.py::test_bbox_confidence_range   PASSED
tests/e2e/test_full_pipeline.py::test_consumer_group_exists   PASSED
tests/e2e/test_full_pipeline.py::test_no_pending_messages     PASSED
tests/e2e/test_full_pipeline.py::test_frames_uploaded_to_s3   PASSED
10 passed in ...
```

### Smoke-test individual services

**EEP health:**
```bash
docker compose exec eep curl -s http://localhost:8000/health
# {"service":"eep","status":"ok"}
```

**gRPC port reachable:**

macOS / Linux:
```bash
docker compose exec eep bash -c "apt-get install -qq netcat-openbsd > /dev/null && nc -zv localhost 50051"
```

Windows (PowerShell):
```powershell
docker compose exec eep python -c "import socket; s=socket.create_connection(('localhost',50051),2); print('gRPC reachable'); s.close()"
```

**Docker socket accessible from EEP:**
```bash
docker compose exec eep python -c "import docker; c=docker.from_env(); print('Docker ping:', c.ping())"
# Docker ping: True
```

**IEP2 DB pool connects:**
```bash
docker compose exec eep python -c "
import asyncio, asyncpg
async def t():
    p = await asyncpg.create_pool('postgresql://retailvision:retailvision_dev@postgres:5432/retailvision')
    print('asyncpg pool ok, size:', p.get_size())
    await p.close()
asyncio.run(t())"
```

**Redis consumer group introspection:**
```bash
docker compose exec redis redis-cli XINFO GROUPS stream:iep1:<camera_id>
```

---

## Environment Variables

All variables have working defaults in `docker-compose.yml` for local development. Override by editing `.env` in the `retail-edge/` directory.

### EEP

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://retailvision:retailvision_dev@postgres:5432/retailvision` | SQLAlchemy async URL |
| `REDIS_URL` | `redis://redis:6379/0` | |
| `S3_ENDPOINT_URL` | `http://minio:9000` | |
| `S3_ACCESS_KEY` | `retailvision` | |
| `S3_SECRET_KEY` | `retailvision_dev` | |
| `S3_BUCKET` | `retailvision` | |
| `JWT_SECRET` | `dev-secret-change-in-production` | **Must be changed in production** |
| `DEBUG_MODE` | `true` | Enables `/api/debug/*` routes — disable in production |
| `IEP2_IMAGE` | `retailvision-iep2:latest` | Docker image used to start IEP2 containers |
| `DOCKER_NETWORK` | `retail-edge_default` | Network IEP2 containers join. Verify: `docker network ls \| grep retail` |

### Edge Agent

| Variable | Required | Default | Description |
|---|---|---|---|
| `EEP_GRPC_URL` | yes | — | `host:50051`, e.g. `eep:50051` |
| `STORE_ID` | yes | — | UUID of the store this agent serves |
| `AGENT_VERSION` | no | `0.1.0` | Reported in heartbeats |
| `IEP1_IMAGE` | no | `retailvision-iep1:latest` | Docker image used to start IEP1 containers |
| `DOCKER_NETWORK` | no | `retail-edge_default` | Network IEP1 containers join |

### IEP1

| Variable | Default | Description |
|---|---|---|
| `S3_ENDPOINT_URL` | — | Frame upload destination |
| `S3_ACCESS_KEY` | — | |
| `S3_SECRET_KEY` | — | |
| `S3_BUCKET` | `retailvision` | |
| `REDIS_URL` | `redis://redis:6379/0` | Manifest publish target |

### IEP2

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql://...` (asyncpg direct, no `+asyncpg` prefix) |
| `REDIS_URL` | — | Consumer group source |
| `S3_ENDPOINT_URL / ACCESS_KEY / SECRET_KEY / BUCKET` | — | Frame download |
| `LIVE_STREAM_ENABLED` | — | Enables LivePublisher (Redis pub/sub for browser live view) |

### Frontend (dev only)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | EEP REST base URL |
| `VITE_LIVE_BRIDGE_URL` | `ws://localhost:8010` | Live bridge WebSocket |
| `VITE_IEP2_DEV_API_URL` | `http://localhost:8002` | Vision Debug Console — IEP2 FastAPI dev server. Only used in dev builds; remove with `VisionDebugConsole.jsx` before shipping. |

---

## gRPC Protocol

EEP and the Edge Agent communicate over a single persistent bidirectional stream defined in `services/eep/proto/agent.proto`.

```
Edge → Cloud:  AgentMessage  { Heartbeat | CameraStatusReport }
Cloud → Edge:  ControlMessage { StartCamera | StopCamera }
```

The first message from any agent **must** be a `Heartbeat`. EEP aborts the stream with `INVALID_ARGUMENT` otherwise.

`StartCamera` carries the full camera config (RTSP URL, FPS, window seconds, S3 config, Redis URL) so the edge agent can start IEP1 with no additional DB calls.

To regenerate stubs after editing the proto (run from `retail-edge/`):

```bash
docker compose run --rm eep python -m grpc_tools.protoc \
  -I services/eep/proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  services/eep/proto/agent.proto
```

Then apply the import fix in `agent_pb2_grpc.py` (replace `import agent_pb2 as agent__pb2` with the package-qualified import) and repeat for `services/edge_agent/`.

---

## Data Flow Summary

```
Camera (RTSP / video file)
  └─ IEP1: frame every 1/fps seconds
       ├─ JPEG → MinIO S3  (key: frames/{camera_id}/{batch}/{ts_ms}.jpg)
       └─ every 60 s: manifest JSON → Redis XADD stream:iep1:{camera_id}
            └─ IEP2: XREADGROUP iep2_workers
                 ├─ Phase A (crash recovery): drain un-ACKed messages at startup
                 ├─ Phase B (normal): block-read new messages (2 s timeout)
                 ├─ per frame: S3 fetch → YOLOv8 → ByteTrack → ReID → homography → shapely
                 └─ INSERT tracking_history (store_id, camera_id, local_id UUID,
                      timestamp_ms, floor_x, floor_y, zone_id, bbox_confidence, bbox_area)
                 └─ XACK after all frames in manifest written to DB
```

`local_id` is stored as a UUID derived deterministically from the integer assigned by `LocalIdentityManager`: `uuid.UUID(int=local_id)`. The same person always maps to the same UUID within a single IEP2 process.

`floor_x`/`floor_y`/`zone_id` are `NULL` when no active homography calibration exists for the camera.

---

## Schema Overview

| Table | Key Columns |
|---|---|
| `tracking_history` | `camera_id TEXT`, `local_id UUID`, `timestamp_ms BIGINT`, `floor_x`, `floor_y`, `zone_id`, `bbox_confidence REAL`, `bbox_area INTEGER` |
| `camera_schedules` | `store_id`, `camera_config_id`, `days_of_week INTEGER[]`, `start_time TIME`, `end_time TIME`, `is_active BOOLEAN` |
| `edge_agents` | `store_id UNIQUE`, `status` (online/offline), `last_heartbeat_at`, `agent_version` |
| `store_config_versions` | `status` (draft/pending_activation/active/archived), `activate_at TIMESTAMPTZ` (set when scheduled), `active_from`, `active_until` |
| `camera_runtime_sessions` | Append-only. `store_id`, `physical_camera_id`, `camera_config_id`, `version_id`, `started_at`, `stopped_at`, `stop_reason` (schedule/manual/version_activation/crash/unknown). FKs: `store_id` → CASCADE; others → SET NULL so history survives hardware/config deletion. |

All pre-existing tables (stores, physical_cameras, camera_configs, calibrations, zones, store_settings, …) are unchanged from the prior schema.

---

## Vision Debug Console (dev only)

A temporary React page for uploading a video, watching live bbox overlays as IEP2 processes it, and scrubbing annotated frames in a playback timeline. Includes a live DB log panel showing `tracking_history` inserts in real time.

**This page is removed before shipping.** To remove it: delete `frontend/src/pages/VisionDebugConsole.jsx` and the corresponding `Route` block in `frontend/src/App.jsx`.

### Running the IEP2 dev server

The FastAPI upload/WebSocket server (`services/iep2_vision/app/main.py`) is intentionally **not** in `docker-compose.yml`. Run it separately alongside the stack:

```bash
# From retail-edge/
uvicorn services.iep2_vision.app.main:app --port 8002 --reload
```

Requires `DATABASE_URL` in the environment (or a local `.env` file in `services/iep2_vision/`):

```bash
DATABASE_URL=postgresql://retailvision:retailvision_dev@localhost:5432/retailvision \
  uvicorn services.iep2_vision.app.main:app --port 8002 --reload
```

### Accessing the page

Start the frontend in dev mode (`npm run dev` in `frontend/`), then open:

**http://localhost:5173/dev/vision**

The page does not appear in any navigation menu — access it directly by URL. It is excluded from production builds (`vite build`) via a conditional dynamic import on `import.meta.env.DEV`.

### Env var

Add to `frontend/.env` (already in `.env.example`):

```
VITE_IEP2_DEV_API_URL=http://localhost:8002
```

---

## MinIO Console

Browse uploaded frames and floor plans at **http://localhost:9001**

| Field | Value |
|---|---|
| Username | `retailvision` |
| Password | `retailvision_dev` |

---

## IEP3 – IEP6 (Skeleton Services)

Four additional pipeline stages exist as Docker skeleton services. They build and start, but contain no implementation logic.

| Service | Port | Planned Function |
|---|---|---|
| `iep3_reconciliation` | 8003 | Cross-camera identity merging |
| `iep4_alerts` | 8004 | Zone occupancy thresholds, dwell-time alerts |
| `iep5_analytics` | 8005 | Aggregated heatmaps, path analysis |
| `iep6_agent` | 8006 | LLM-powered natural language insights |

Start all skeletons alongside the live services:

```bash
docker compose up -d
```

---

## Troubleshooting

**Edge Agent logs `NOT_FOUND` and keeps reconnecting after a fresh DB**

After `docker compose down -v`, the database is wiped but the Edge Agent's `STORE_ID` in `.env` still refers to the deleted store. EEP rejects the gRPC connection with `NOT_FOUND` until the store is recreated via the API. The agent retries with exponential backoff (1 s → 60 s cap) and reconnects automatically within 60 seconds of store creation — no manual restart needed.

**EEP can't reach Docker socket**

Ensure `/var/run/docker.sock` is mounted (set in `docker-compose.yml`). On Linux, verify your user is in the `docker` group. On Docker Desktop for Mac/Windows, the socket is automatically available.

**Edge Agent can't connect to EEP gRPC**

Check `EEP_GRPC_URL` — inside Docker Compose it should be `eep:50051`, not `localhost:50051`.

```bash
docker compose logs edge_agent | grep "Connection failed"
```

**IEP2 containers not starting**

Check EEP logs for orchestrator errors:

```bash
docker compose logs eep | grep -i "iep2\|orchestrat\|docker"
```

Ensure `IEP2_IMAGE` is built:

```bash
docker images | grep iep2
```

**No rows in `tracking_history`**

1. Verify IEP2 is running: `docker ps --filter "name=iep2_"`
2. Check Redis stream has messages: `docker compose exec redis redis-cli XLEN stream:iep1:<camera_id>`
3. Check IEP2 logs for YOLO/DB errors: `docker logs iep2_<store>_<cam>`
4. Verify homography calibration exists (floor_x/floor_y will be NULL without it — rows are still written)

**`DOCKER_NETWORK` mismatch**

The default Compose network name is `retail-edge_default`. If you cloned to a different directory the project name changes.

```bash
docker network ls | grep retail
```

Set `DOCKER_NETWORK` in `.env` to the actual network name.

**Re-running after schema changes**

```bash
docker compose down -v          # removes all volumes including postgres data
docker compose up -d --build    # full rebuild and fresh schema
```
