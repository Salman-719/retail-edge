# RetailVision

Multi-camera retail analytics platform. Tracks customers across cameras in real-time, measures zone occupancy, and produces canonical per-person trajectories for analytics.

---

## Architecture

```
CLOUD (Kubernetes / Docker Compose)
┌──────────────────────────────────────────────────────────────────────┐
│  React Frontend :3000                                                │
│         │ HTTP REST                                                  │
│  EEP  :8000 (REST) + :50051 (gRPC TLS)                              │
│  FastAPI · SQLAlchemy asyncpg · APScheduler · grpc.aio              │
│  Sends StartCamera/StopCamera to Edge Agent over gRPC stream        │
│                                                                      │
│  IEP3 Reconciliation (daemon, no port)                               │
│  Consumes stream:iep2:batch_complete → cross-camera ReID            │
│  → global_identities / global_tracking_history                      │
│                                                                      │
│  Live Bridge :8010  WebSocket → presigned S3 URLs                   │
│  PostgreSQL + PgBouncer · Server Redis · MinIO (S3)                  │
└──────────────────────┬───────────────────────────────────────────────┘
                       │ gRPC TLS :50051 (edge dials out, stream stays open)
┌──────────────────────▼───────────────────────────────────────────────┐
│  EDGE DEVICE (k3s / Jetson)                                          │
│                                                                      │
│  Edge Agent (systemd · thin gRPC relay)                              │
│    Translates StartCamera/StopCamera → k3s kubectl apply            │
│    Manages per-camera IEP2 Deployments + ConfigMaps                 │
│                                                                      │
│  IEP1 daemon (k3s pod, one process for all cameras)                 │
│    RTSP/video → JPEG frames → tmpfs → Redis XADD stream:iep1:{cam}  │
│    60-second window manifests → edge-local Redis                    │
│                                                                      │
│  IEP2 vision (one k3s Deployment per camera, created by Edge Agent)  │
│    XREADGROUP iep1-frames → YOLO → ByteTrack → ReID → homography    │
│    → INSERT tracking_history → XADD stream:iep2:batch_complete      │
│                                                                      │
│  YOLO service + OSNet service (GPU, unix socket IPC)                 │
│  Edge-local Redis (loopback-only, ephemeral)                         │
└──────────────────────────────────────────────────────────────────────┘

Redis topology
  Edge-local Redis  127.0.0.1:6379   stream:iep1:{camera_id}   (ephemeral)
  Server Redis      redis:6379        stream:iep2:batch_complete (persistent)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, React Router v6, Konva.js, Zustand, Tailwind CSS |
| API Gateway (EEP) | FastAPI 0.115, SQLAlchemy 2 async, Pydantic v2, APScheduler 3.10 |
| Edge-Cloud Comms | gRPC (grpcio 1.64, TLS + shared-secret auth, bidirectional streaming) |
| Computer Vision | YOLOv8 (Ultralytics), ByteTrack (boxmot), OSNet ReID |
| Floor Projection | NumPy homography, Shapely polygons |
| Database | PostgreSQL 16 + PgBouncer 1.22, asyncpg 0.29 |
| Cache / Streams | Redis 7.2 (XREADGROUP consumer groups, topology-split) |
| Object Storage | MinIO (S3-compatible), boto3 |
| Edge Orchestration | k3s 1.29, kubernetes Python client |
| Cloud Deployment | Helm 3.14, cert-manager, external-secrets |
| Containerisation | Docker, Docker Compose |

---

## Project Structure

```
retail-edge/
├── docker-compose.yml           # Full local dev stack
├── docker-compose.dev.yml       # Dev overrides (DEBUG_MODE=true)
├── charts/retailvision/         # Server-side Helm chart
├── infra/
│   ├── edge/base/               # k3s edge manifests (namespace, RBAC, inference services)
│   ├── pgbouncer/               # PgBouncer config
│   └── redis-local.conf         # Edge-local Redis config (loopback, ephemeral)
├── scripts/
│   ├── gen_dev_certs.sh         # Generate dev TLS certs (CA + EEP server cert)
│   └── bootstrap-edge-k3s.sh   # Bootstrap a Jetson device with k3s
├── docs/
│   ├── decisions/               # Architecture Decision Records
│   └── operations/              # Operational runbooks
├── services/
│   ├── eep/                     # EEP: REST API + gRPC server + scheduler
│   ├── edge_agent/              # Thin gRPC relay → k3s API
│   ├── iep1_ingestion/          # Camera ingestion daemon
│   ├── iep2_vision/             # Per-camera YOLO+ByteTrack+ReID worker
│   ├── iep3_reconciliation/     # Cross-camera identity reconciliation daemon
│   ├── live_bridge/             # WebSocket live frame relay
│   ├── yolo_service/            # YOLO gRPC inference service (GPU)
│   └── osnet_service/           # OSNet ReID embedding service (GPU)
└── tests/
    ├── unit/iep3/               # IEP3 pure-logic unit tests (no infrastructure)
    └── e2e/                     # Integration + end-to-end tests
```

---

## Prerequisites

- **Docker Desktop** (includes Docker Compose v2)
- **Git**
- **bash** (for the cert-generation script — Git Bash on Windows)

No local Python or Node.js install required. All services run inside Docker.

> **Linux Docker socket:** On Linux add your user to the `docker` group: `sudo usermod -aG docker $USER`, then log out and back in.

---

## Quick Start — Local Dev Stack

### 1. Clone

```bash
git clone <repo-url>
cd retail-edge
```

### 2. Configure environment

```bash
# macOS/Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

The defaults in `.env` work for local development — no edits needed. All services run in **dev mode** (gRPC TLS disabled, no auth check) unless you generate certs (see [Generating Dev TLS Certs](#generating-dev-tls-certs) below).

### 3. Build images

```bash
docker compose build
```

First build takes several minutes (YOLO, OpenCV, grpcio, k8s client).

### 4. Start infrastructure + server services

```bash
docker compose up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge
```

Wait for healthy status:

```bash
docker compose ps
```

EEP first startup automatically runs schema migrations and creates the MinIO bucket.

### 5. Start the edge stack (dev mode — same machine)

```bash
docker compose --profile edge up -d iep1-daemon yolo-service osnet-service edge_agent_dev
```

### 6. Start the frontend

```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**. API docs at **http://localhost:8000/docs**.

---

## Generating Dev TLS Certs

For local dev, gRPC runs **insecure** by default (no certs needed). For testing TLS locally:

```bash
bash scripts/gen_dev_certs.sh
```

This creates under `certs/`:
```
certs/ca.crt          CA certificate
certs/eep.crt         EEP server certificate (SAN: localhost, 127.0.0.1)
certs/eep.key         EEP server private key
```

Then set in your `.env` (or override in `docker-compose.dev.yml`):

```
GRPC_SERVER_CERT_PATH=/certs/eep.crt
GRPC_SERVER_KEY_PATH=/certs/eep.key
AGENT_SECRET=your-shared-secret-here
GRPC_CA_CERT_PATH=/certs/ca.crt
```

Mount the `certs/` directory into the `eep` and `edge_agent_dev` containers:
```yaml
# docker-compose.dev.yml
services:
  eep:
    volumes:
      - ./certs:/certs:ro
  edge_agent_dev:
    volumes:
      - ./certs:/certs:ro
    environment:
      GRPC_CA_CERT_PATH: /certs/ca.crt
```

---

## Running Each Service Standalone

Each service can be run in isolation for development and testing. All commands assume infrastructure (Postgres, Redis, MinIO) is running.

### Start infrastructure only

```bash
docker compose up -d postgres pgbouncer redis minio
```

---

### EEP (Enterprise Event Processor)

**What it does:** REST API + gRPC server. Manages stores, cameras, schedules, calibrations. Sends `StartCamera`/`StopCamera` to edge agents.

**Start with Compose:**
```bash
docker compose up eep
```

**Run locally (outside Docker):**
```bash
cd services/eep
pip install -e .[dev]

WINDOW_SECONDS=60 \
DATABASE_URL_EEP=postgresql+asyncpg://retailvision:retailvision_dev@localhost:5433/retailvision \
REDIS_URL=redis://localhost:6379/0 \
S3_ACCESS_KEY=retailvision \
S3_SECRET_KEY=retailvision_dev \
JWT_SECRET=dev-secret \
AGENT_SECRET=dev-agent-secret \
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Smoke test:**
```bash
curl http://localhost:8000/health
# {"service":"eep","status":"ok"}
```

**gRPC port check:**
```bash
docker compose exec eep python -c "
import socket
s = socket.create_connection(('localhost', 50051), 2)
print('gRPC port reachable')
s.close()
"
```

**Run EEP unit/API tests:**
```bash
docker compose run --rm eep pytest services/eep/tests/ -v
```

---

### IEP1 Ingestion Daemon

**What it does:** Single daemon process managing all cameras on the edge device. Reads RTSP/video frames, uploads JPEGs to tmpfs, publishes 60-second window manifests to edge-local Redis.

**Start with Compose:**
```bash
docker compose up iep1-daemon
```

**Process a local video file directly (CLI mode):**
```bash
docker compose run --rm \
  -e LOCAL_REDIS_URL=redis://redis:6379/0 \
  -e STORE_ID=00000000-0000-0000-0000-000000000001 \
  -v $(pwd)/testing-data:/testing-data:ro \
  iep1-daemon \
  python -m services.iep1_ingestion.app.main \
    --source video \
    --file /testing-data/sample.mp4 \
    --camera-id 00000000-0000-0000-0000-000000000002
```

**Verify Redis stream after one window (60 s):**
```bash
docker compose exec redis redis-cli XLEN stream:iep1:00000000-0000-0000-0000-000000000002
# > 1 (one batch manifest)
```

**Logs:**
```bash
docker compose logs -f iep1-daemon
```

---

### IEP2 Vision Worker

**What it does:** Per-camera YOLO → ByteTrack → OSNet ReID → homography → `tracking_history`. One Deployment per active camera (created by Edge Agent on k3s; one compose service in dev).

**Start with Compose (requires `CAMERA_ID`):**
```bash
CAMERA_ID=<physical_camera_uuid> docker compose up iep2_vision
```

**Process a local video file (daemon mode reading from Redis):**
```bash
docker compose run --rm \
  -e CAMERA_ID=00000000-0000-0000-0000-000000000002 \
  -e STORE_ID=00000000-0000-0000-0000-000000000001 \
  -e LOCAL_REDIS_URL=redis://redis:6379/0 \
  -e SERVER_REDIS_URL=redis://redis:6379/0 \
  -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
  iep2_vision
```

**Verify tracking rows after one batch:**
```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT COUNT(*), MIN(timestamp_ms), MAX(timestamp_ms) FROM tracking_history;"
```

**IEP2 Dev Console (video upload + live bbox overlay):**
```bash
docker compose --profile dev up -d iep2_dev
# Then open http://localhost:5173/dev/vision
```

**Logs:**
```bash
docker compose logs -f iep2_vision
```

---

### IEP3 Reconciliation

**What it does:** Cross-camera identity reconciliation daemon. Consumes `stream:iep2:batch_complete`, runs ReID matching, maintains `global_identities` and `global_tracking_history`. No HTTP port.

**Start with Compose:**
```bash
STORE_ID=<store_uuid> docker compose up iep3_reconciliation
```

IEP3 reads the expected camera count from the database — no `EXPECTED_CAMERAS` env var needed.

**Verify startup:**
```bash
docker compose logs iep3_reconciliation | head -20
# Expected:
# IEP3 starting  store_id=...  window_seconds=60.0
# DB verified — all required tables present.
# Redis verified.
# Orphan sweep clean  {"store_id": "...", "deleted_globals": 0, "deleted_centroids": 0}
# PEL health: 0 pending entries for group iep3-...
# IEP3 ready — listening on stream:iep2:batch_complete
```

**After batches are reconciled:**
```bash
docker compose exec postgres psql -U retailvision -d retailvision -c "
SELECT
  (SELECT count(*) FROM global_identities WHERE state='active')    AS active_globals,
  (SELECT count(*) FROM global_local_mapping WHERE is_active=TRUE) AS active_links,
  (SELECT count(*) FROM global_tracking_history)                    AS canonical_positions;"
```

**Run IEP3 unit tests (no DB/Redis required):**
```bash
docker compose run --rm iep3_reconciliation pytest tests/unit/iep3/ -v
# Expected: 25 tests pass (gate: 8, matcher: 6, selector: 5, state: 6)
```

**Run IEP3 integration test (requires Postgres):**
```bash
docker compose run --rm \
  -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
  iep3_reconciliation pytest tests/e2e/test_iep3_reconciler.py -v -s
# Expected: 2 tests pass — full 3-camera reconciliation scenario
```

---

### Live Bridge

**What it does:** Bridges `stream:iep2:live:{camera_id}` (server Redis) to WebSocket clients. Presigns S3 frame URLs. One background task per camera, starts on first client connection.

**Start with Compose:**
```bash
docker compose up live_bridge
```

**Smoke test:**
```bash
curl http://localhost:8010/health
# {"status":"ok"}
```

**WebSocket test (requires a running camera):**
```bash
# Connect to the live feed for a camera
websocat ws://localhost:8010/ws/live/<physical_camera_uuid>
# Should receive JSON frames: {"camera_id":..., "frame_url":..., "detections":[...]}
```

---

### Edge Agent (dev mode)

**What it does:** Thin gRPC relay. Translates `StartCamera`/`StopCamera` commands from EEP into `k3s kubectl apply` operations. In dev mode, runs alongside the main stack and uses Docker/Compose instead of real k3s.

**Start with Compose:**
```bash
docker compose --profile edge up edge_agent_dev
```

**Verify connection:**
```bash
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT store_id, status, last_heartbeat_at, agent_version FROM edge_agents;"
# Expected: one row with status = online
```

**Logs:**
```bash
docker compose logs -f edge_agent_dev
# Expected every 30 s: heartbeat sent  store_id=...
```

---

## Running the Full Local Pipeline

### Step 1 — Start everything

```bash
docker compose up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge
docker compose --profile edge up -d iep1-daemon yolo-service osnet-service edge_agent_dev
```

### Step 2 — Create a store, add cameras, configure schedules

Use the frontend at **http://localhost:5173** (onboarding wizard steps 1–9) or the API at **http://localhost:8000/docs**.

### Step 3 — Trigger a camera manually

```bash
curl -s -X POST http://localhost:8000/api/debug/agent/command \
  -H "Content-Type: application/json" \
  -d '{
    "store_id":   "<store_uuid>",
    "camera_id":  "<physical_camera_uuid>",
    "action":     "start",
    "rtsp_url":   "rtsp://your-camera/stream"
  }'
```

> Requires `DEBUG_MODE=true` — enabled in `docker-compose.dev.yml`.

### Step 4 — Verify the pipeline

```bash
# IEP1: check manifest published
docker compose exec redis redis-cli XLEN stream:iep1:<camera_uuid>

# IEP2: check tracking rows (after ~60 s)
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT COUNT(*) FROM tracking_history WHERE camera_id='<camera_uuid>';"

# IEP3: check global identities (after IEP2 fires batch_complete)
docker compose exec postgres psql -U retailvision -d retailvision \
  -c "SELECT count(*), state FROM global_identities GROUP BY state;"
```

---

## Testing

### Unit tests — IEP3 (no infrastructure)

```bash
docker compose run --rm iep3_reconciliation pytest tests/unit/iep3/ -v
```

| Test file | What it tests | Count |
|---|---|---|
| `test_gate.py` | `cross_camera_gate` pure function (speed, NULL coords) | 8 |
| `test_matcher.py` | `ReidMatcher` cosine similarity + GlobalID linking | 6 |
| `test_selector.py` | `PositionSelector` scoring + canonical position | 5 |
| `test_state.py` | `StateManager` ACTIVE→LOST→EXITED transitions | 6 |

### Integration test — IEP3 3-camera reconciliation (requires Postgres)

```bash
docker compose up -d postgres pgbouncer
docker compose run --rm \
  -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
  iep3_reconciliation pytest tests/e2e/test_iep3_reconciler.py -v -s
```

No Redis, IEP1, IEP2, or EEP needed. Test data is cleaned up via CASCADE delete.

### End-to-end test — full pipeline (requires running stack)

**Prerequisites:**
- Full stack running (step 1 of full pipeline above)
- Edge Agent online (`status = online` in `edge_agents`)
- A camera triggered and running for at least 60 seconds

```bash
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
  -e REDIS_URL=redis://redis:6379/0 \
  -e S3_ENDPOINT_URL=http://minio:9000 \
  -e S3_ACCESS_KEY=retailvision \
  -e S3_SECRET_KEY=retailvision_dev \
  -e S3_BUCKET=retailvision \
  -e E2E_CAMERA_ID=<physical_camera_uuid> \
  -e E2E_STORE_ID=<store_uuid> \
  eep pytest tests/e2e/test_full_pipeline.py -v
```

> `E2E_CAMERA_ID` is `physical_cameras.id` — not `camera_configs.id`. These are different UUIDs.

**Expected output: 10 tests pass** — rows exist, IDs are UUIDs, floor coords populated, S3 frames present, consumer group exists, no pending messages.

---

## Environment Variables Reference

### Shared (all pipeline services)

| Variable | Default | Description |
|---|---|---|
| `WINDOW_SECONDS` | `60` | Batch window in seconds — must be identical across IEP1, IEP2, IEP3 |
| `DATABASE_URL_SERVER` | auto | `postgresql://...@pgbouncer:5432/retailvision` (asyncpg direct, no `+asyncpg`) |

### EEP

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL_EEP` | required | `postgresql+asyncpg://...` (SQLAlchemy async dialect) |
| `REDIS_URL` | `redis://redis:6379/0` | Server Redis |
| `JWT_SECRET` | required | **Change in production** |
| `S3_ENDPOINT_URL / ACCESS_KEY / SECRET_KEY / BUCKET` | required | MinIO / S3 |
| `GRPC_PORT` | `50051` | gRPC listen port |
| `GRPC_SERVER_CERT_PATH` | `` (empty) | PEM cert path — empty = insecure dev mode |
| `GRPC_SERVER_KEY_PATH` | `` (empty) | PEM key path — empty = insecure dev mode |
| `AGENT_SECRET` | `` (empty) | Shared secret for edge agents — empty = no auth (dev) |
| `DEBUG_MODE` | `false` | Enables `/api/debug/*` routes — disable in production |
| `IEP2_IMAGE` | `retailvision-iep2:latest` | Docker image for IEP2 containers (legacy compose mode) |

### Edge Agent

| Variable | Default | Description |
|---|---|---|
| `EEP_GRPC_URL` | required | `host:50051` |
| `STORE_ID` | required | UUID of the store this agent serves |
| `AGENT_SECRET` | `` (empty) | Must match EEP's `AGENT_SECRET` |
| `GRPC_CA_CERT_PATH` | `/etc/retailvision/certs/ca.crt` | CA cert for TLS — missing file = insecure (dev) |
| `SERVER_REDIS_URL` | `` | Passed to IEP2 ConfigMaps |
| `DATABASE_URL_SERVER` | `` | Passed to IEP2 ConfigMaps |
| `LOCAL_REDIS_URL` | `redis://localhost:6379/0` | Passed to IEP1 |
| `HEARTBEAT_INTERVAL_S` | `30` | |

### IEP1 Ingestion Daemon

| Variable | Default | Description |
|---|---|---|
| `LOCAL_REDIS_URL` | `redis://127.0.0.1:6379/0` | Edge-local Redis (loopback) |
| `IEP1_CONTROL_SOCK` | `unix:///dev/shm/sockets/iep1_control.sock` | gRPC control socket |
| `IEP1_HEALTH_SOCK` | `unix:///dev/shm/sockets/iep1_health.sock` | gRPC health socket |
| `TMPFS_FRAME_ROOT` | `/dev/shm/frames` | Shared frame store path |

### IEP2 Vision Worker

| Variable | Required | Description |
|---|---|---|
| `CAMERA_ID` | yes | `physical_cameras.id` UUID |
| `STORE_ID` | yes | |
| `CAMERA_CONFIG_ID` | no | Set by Edge Agent; enables homography reload |
| `LOCAL_REDIS_URL` | yes | Edge-local Redis (reads IEP1 stream) |
| `SERVER_REDIS_URL` | yes | Server Redis (publishes `batch_complete`) |
| `DATABASE_URL_SERVER` | yes | `postgresql://...` (no `+asyncpg` prefix) |
| `YOLO_INPUT_SOCK` | yes | ZMQ IPC socket for YOLO inference |
| `OSNET_INPUT_SOCK` | yes | ZMQ IPC socket for OSNet inference |
| `TMPFS_FRAME_ROOT` | yes | Shared frame store path (reads IEP1 files) |

### IEP3 Reconciliation

| Variable | Default | Description |
|---|---|---|
| `STORE_ID` | required | Store UUID — one IEP3 instance per store |
| `WINDOW_SECONDS` | required | Must match IEP1/IEP2 |
| `DATABASE_URL_SERVER` | required | `postgresql://...` (no `+asyncpg`) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | Server Redis (reads `batch_complete` stream) |
| `REID_THRESHOLD` | `0.75` | Cosine similarity threshold |
| `MAX_SPEED_MPS` | `1.5` | Spatial gate max walking speed |
| `GRACE_SECONDS` | `300.0` | LOST → EXITED grace period |
| `EMBEDDING_DIM` | `512` | OSNet embedding dimension |
| `CENTROID_EMA_ALPHA` | `0.3` | EMA smoothing for embedding updates |
| `COORDINATOR_TIMEOUT_S` | `120.0` | Partial-batch timeout |
| `POSITION_WEIGHT_AREA` | `0.7` | Canonical position scoring: bbox area weight |
| `POSITION_WEIGHT_CONF` | `0.3` | Canonical position scoring: detection confidence weight |
| `EXPECTED_CAMERAS_REFRESH_BATCHES` | `10` | How often to re-query DB for camera count |
| `ORPHAN_SWEEP_INTERVAL_BATCHES` | `50` | How often to run orphan sweep (batches) |

### Live Bridge

| Variable | Default | Description |
|---|---|---|
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | Server Redis (reads `stream:iep2:live:{cam}`) |
| `S3_ENDPOINT_URL / ACCESS_KEY / SECRET_KEY / BUCKET` | required | Frame URL presigning |
| `PRESIGNED_URL_EXPIRY` | `30` | Seconds until presigned URL expires |

---

## Deployment

### Local Docker Compose

The default `docker-compose.yml` runs the full stack with dev defaults. For debugging with `DEBUG_MODE=true` and live reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Cloud — Server (Helm)

Prerequisites: Kubernetes cluster, `cert-manager`, `external-secrets` installed.

```bash
# Dry run
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.staging.yaml \
  --namespace retailvision \
  --create-namespace \
  --dry-run

# Deploy staging
helm upgrade --install retailvision ./charts/retailvision \
  -f charts/retailvision/values.staging.yaml \
  --namespace retailvision

# Verify EEP
kubectl rollout status deployment/eep -n retailvision --timeout=120s
kubectl get pods -n retailvision
```

Add stores to IEP3:
```bash
helm upgrade retailvision ./charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --set "iep3.stores={store-uuid-1,store-uuid-2}" \
  --namespace retailvision
```

### Cloud — Edge Device (k3s bootstrap)

Run from the repo root on the Jetson device:

```bash
sudo bash scripts/bootstrap-edge-k3s.sh \
  <store_uuid> \
  <image_version> \
  <eep_hostname_or_ip> \
  <agent_secret>
```

This installs k3s (API server loopback-only), applies `infra/edge/base/` manifests, writes the edge agent env file, and installs the systemd service. After bootstrap:

```bash
# Verify edge services
k3s kubectl get pods -n retailvision

# Verify edge agent connected
journalctl -u retailvision-edge-agent -f
```

### Updating edge images (zero-downtime rolling update)

```bash
k3s kubectl set image deployment/yolo-service \
  yolo-service=retailvision-yolo-service:1.1.0 \
  -n retailvision
k3s kubectl rollout status deployment/yolo-service -n retailvision
```

For IEP2 pods (managed per-camera by Edge Agent):
```bash
# Update the IEP2_IMAGE env var in the edge agent, then restart it
# The next StartCamera command will use the new image
systemctl restart retailvision-edge-agent
```

---

## Monitoring & Logs

### Service logs

```bash
docker compose logs -f eep               # REST API + gRPC + scheduler
docker compose logs -f edge_agent_dev    # heartbeats + K8s operations
docker compose logs -f iep1-daemon       # frame upload + batch windows
docker compose logs -f iep2_vision       # detections + DB writes
docker compose logs -f iep3_reconciliation  # reconciliation + orphan sweep
```

### Check Redis streams

```bash
# IEP1 output (edge-local stream)
docker compose exec redis redis-cli XLEN stream:iep1:<camera_uuid>

# IEP2 output (batch_complete on server Redis)
docker compose exec redis redis-cli XLEN stream:iep2:batch_complete

# IEP3 consumer group state
docker compose exec redis redis-cli XINFO GROUPS stream:iep2:batch_complete
# Look for iep3-<store_uuid> entry; "lag" should be 0
```

### Check pending messages (should be 0 after processing)

```bash
docker compose exec redis redis-cli XPENDING \
  stream:iep2:batch_complete iep3-<store_uuid>
# In XACK-before-processing model, PEL should always be empty
```

### Check tracking data

```bash
docker compose exec postgres psql -U retailvision -d retailvision -c "
SELECT camera_id, COUNT(*), MIN(floor_x IS NOT NULL)
FROM tracking_history GROUP BY camera_id;"
```

### Check global identities (IEP3 output)

```bash
docker compose exec postgres psql -U retailvision -d retailvision -c "
SELECT state, COUNT(*) FROM global_identities GROUP BY state;"
```

### MinIO Console

**http://localhost:9001** — username: `retailvision`, password: `retailvision_dev`

---

## Data Flow

```
Camera (RTSP / video file)
└─ IEP1 daemon: frame every 1/fps s
     ├─ JPEG → tmpfs /dev/shm/frames/{cam}/{ts}.jpg
     └─ every 60 s: manifest JSON → edge-local Redis XADD stream:iep1:{camera_id}
          └─ IEP2 vision: XREADGROUP iep1-frames
               ├─ Phase A (startup): drain un-ACKed messages
               ├─ Phase B (normal): block-read new messages
               ├─ per manifest: tmpfs read → YOLO → ByteTrack → OSNet → homography
               ├─ INSERT tracking_history + UPSERT local_centroids
               ├─ XADD server-Redis stream:iep2:batch_complete
               └─ XACK edge-local-Redis stream:iep1:{camera_id}
                    └─ IEP3: XREADGROUP iep3-{store_id} ← stream:iep2:batch_complete
                         ├─ XACK immediately (before processing — see ADR-001)
                         ├─ BatchCoordinator: wait N cameras or timeout
                         └─ Reconciler (one asyncpg transaction per batch):
                              ├─ BatchReader: classify known vs new LocalIDs
                              ├─ ReidMatcher: cosine ReID → link/create GlobalIDs
                              ├─ PositionSelector: score → INSERT global_tracking_history
                              └─ StateManager: ACTIVE→LOST→EXITED
```

`local_id` is a UUID derived from the ByteTrack integer: `uuid.UUID(int=track_id)`.
`floor_x`/`floor_y`/`zone_id` are `NULL` until a homography calibration exists.

---

## Schema

### IEP1/IEP2 tables

| Table | Key columns |
|---|---|
| `tracking_history` | `camera_id`, `local_id UUID`, `timestamp_ms BIGINT`, `floor_x/y`, `zone_id`, `bbox_confidence`, `bbox_area` |
| `local_centroids` | `local_id UUID PK`, `store_id UUID`, `centroid BYTEA` (float32[512]) |
| `camera_schedules` | `store_id`, `camera_config_id`, `days_of_week`, `start_time`, `end_time`, `is_active` |
| `edge_agents` | `store_id UNIQUE`, `status`, `last_heartbeat_at`, `agent_version` |
| `camera_runtime_sessions` | `store_id`, `physical_camera_id`, `started_at`, `stopped_at`, `stop_reason` |

### IEP3 tables (cross-camera identity)

| Table | Key columns |
|---|---|
| `global_identities` | `global_id UUID PK`, `store_id`, `state` (active/lost/exited), `first/last_seen_ts`, `last_floor_x/y`, `entry/exit_zone_id` |
| `global_local_mapping` | `global_id`, `local_id`, `camera_id`, `is_active BOOL` — partial unique index on active `(global_id, camera_id)` |
| `global_embeddings` | `(global_id, camera_id) PK`, `centroid BYTEA` |
| `global_tracking_history` | `global_id`, `batch_number`, `timestamp_ms`, `floor_x/y`, `source_camera`, `selection_score` |

---

## gRPC Protocol

```
Edge → Cloud:  AgentMessage  { Heartbeat | CameraStatusReport }
Cloud → Edge:  ControlMessage { StartCamera | StopCamera }
```

First message from any agent **must** be a `Heartbeat`. EEP aborts with `INVALID_ARGUMENT` otherwise.

Auth: each RPC carries `x-agent-token: <shared_secret>` metadata. Empty `AGENT_SECRET` disables auth (dev mode).

Regenerate stubs after editing `services/eep/proto/agent.proto`:

```bash
docker compose run --rm eep python -m grpc_tools.protoc \
  -I services/eep/proto \
  --python_out=services/eep/app/grpc_generated \
  --grpc_python_out=services/eep/app/grpc_generated \
  services/eep/proto/agent.proto
# Then fix the relative import in agent_pb2_grpc.py and repeat for services/edge_agent/
```

---

## Troubleshooting

**Edge Agent logs `NOT_FOUND` and keeps reconnecting**
After `docker compose down -v` the DB is wiped but `STORE_ID` in `.env` still refers to the deleted store. Recreate the store via the API — the agent reconnects automatically (exponential backoff, 1 s → 60 s cap).

**EEP won't start — `GRPC_SERVER_CERT_PATH` validation error**
In dev mode, leave `GRPC_SERVER_CERT_PATH` and `GRPC_SERVER_KEY_PATH` empty (the default). EEP will start with gRPC insecure. If you get `GRPC_SERVER_CERT_PATH` errors, check that the fields in `config.py` have `Field(default="")` not `Field(...)`.

**Edge Agent can't connect to EEP gRPC**
Inside Docker Compose use `eep:50051`, not `localhost:50051`. Check `EEP_GRPC_URL` in `.env`.
```bash
docker compose logs edge_agent_dev | grep "Connecting to EEP"
```

**IEP3 orphan sweep warnings on startup**
Normal after a crash — IEP3 cleaned up partial state left by the previous process. Expect `deleted_globals` and `deleted_centroids` to be small non-zero numbers immediately after a restart. Both return to 0 after the next periodic sweep.

**IEP3 `SERVER_REDIS_URL` not connecting**
IEP3 reads `SERVER_REDIS_URL` (not `REDIS_URL`). Confirm the compose service gets it from the `*shared-config` anchor:
```bash
docker compose exec iep3_reconciliation env | grep REDIS
# SERVER_REDIS_URL=redis://redis:6379/0
```

**No rows in `tracking_history` after 60 s**
1. `docker compose exec redis redis-cli XLEN stream:iep1:<camera_uuid>` — must be > 0 (IEP1 published a batch)
2. Check IEP2 logs: `docker compose logs iep2_vision | grep -i "error\|batch"`
3. Verify `CAMERA_ID` env var matches the camera UUID IEP1 published to

**PgBouncer `SET` errors in IEP3**
IEP3 uses asyncpg direct queries with per-query timeouts (`conn.fetch(..., timeout=120.0)`) — no `SET statement_timeout`. If you see SET errors, something is bypassing the repository layer and using raw psycopg2.

**`DOCKER_NETWORK` mismatch**
Default Compose network is `retail-edge_default`. If you cloned to a different directory, the project name changes.
```bash
docker network ls | grep retail
# Set DOCKER_NETWORK in .env to the actual network name
```

**Full reset**
```bash
docker compose down -v          # wipes all volumes including postgres data
docker compose up -d --build    # fresh rebuild and schema migration
```
