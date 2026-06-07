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
│    XREADGROUP iep1-frames → RT-DETR → BoTSORT → ReID → homography   │
│    → INSERT tracking_history → XADD stream:iep2:batch_complete      │
│                                                                      │
│  YOLO service + ReID service (GPU, unix socket IPC)                 │
│  Edge-local Redis (loopback-only, ephemeral)                         │
└──────────────────────────────────────────────────────────────────────┘

Redis topology
  Edge-local Redis  127.0.0.1:6379   stream:iep1:{camera_id}   (ephemeral)
  Server Redis      redis:6379        stream:iep2:batch_complete (persistent)
```

---

## Documentation & MLOps

| Doc | What it covers |
|---|---|
| [`docs/MLFLOW_GUIDE.md`](docs/MLFLOW_GUIDE.md) | MLflow setup + how to run the offline model experiments |
| [`docs/MLOPS_PIPELINE.md`](docs/MLOPS_PIPELINE.md) | Lifecycle: CI, experiment tracking, promotion gate + model registry |
| [`docs/docs_models/detection/DETECTION_RESULTS.md`](docs/docs_models/detection/DETECTION_RESULTS.md) | Detection experiment — 24 runs, model comparison + decision |
| [`docs/DETECTION_SCREENSHOTS.md`](docs/DETECTION_SCREENSHOTS.md) | MLflow screenshots (runs, comparison, mannequin rejection, registry) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, React Router v6, Konva.js, Zustand, Tailwind CSS |
| API Gateway (EEP) | FastAPI 0.115, SQLAlchemy 2 async, Pydantic v2, APScheduler 3.10 |
| Edge-Cloud Comms | gRPC (grpcio 1.64, TLS + shared-secret auth, bidirectional streaming) |
| Computer Vision | RT-DETR (Ultralytics), BoTSORT (boxmot), resnet50_msmt17 ReID (boxmot) |
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
│   ├── iep2_vision/             # Per-camera RT-DETR+BoTSORT+ReID worker
│   ├── iep3_reconciliation/     # Cross-camera identity reconciliation daemon
│   ├── live_bridge/             # WebSocket live frame relay
│   ├── yolo_service/            # YOLO gRPC inference service (GPU)
│   └── reid_service/           # resnet50_msmt17 ReID embedding service (GPU)
└── tests/
    ├── unit/iep3/               # IEP3 pure-logic unit tests (no infrastructure)
    └── e2e/                     # Integration + end-to-end tests
```

---

## Prerequisites

- **Docker Desktop** (includes Docker Compose v2)
- **Git**
- **bash** (for the cert-generation script — Git Bash on Windows)
- **Node.js 18+ / npm** — only if you use the **dev pipeline screens** (`/dev/e2e`,
  `/dev/vision`), which require the Vite dev server (`npm run dev`). Not needed for
  the production Docker frontend on `:3000`.

The backend runs entirely in Docker — no local Python required.

> **Linux Docker socket:** On Linux add your user to the `docker` group: `sudo usermod -aG docker $USER`, then log out and back in.

> **GPU inference is off by default** (services run on CPU). To run the detector +
> ReID on an **NVIDIA** GPU — including installing the driver and NVIDIA Container
> Toolkit — follow [Running inference on a GPU (NVIDIA)](#running-inference-on-a-gpu-nvidia).
> Intel GPUs are not supported via Docker (see that section).

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

**Windows (PowerShell):**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml build
```

**macOS / Linux:**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml build
```

> **Why the dev overlay?** The base `docker-compose.yml` builds YOLO and ReID
> from Jetson/ARM64 JetPack base images that cannot build or run on x86.
> `docker-compose.dev.yml` overrides both to CPU/GPU dev variants (Ultralytics
> RT-DETR-x for detection; resnet50_msmt17 via boxmot for ReID). The dev
> override must always be included on any non-Jetson machine.

First build takes several minutes (model download, OpenCV, grpcio, k8s client).

### 4. Start infrastructure + server services

**Windows (PowerShell):**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge
```

**macOS / Linux:**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge
```

Wait for healthy status:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

EEP first startup automatically runs Alembic schema migrations. Allow 30–60 s for YOLO model load.

### 5. Start the edge inference services

YOLO and ReID must be running before IEP1 or IEP2 can start.

**Windows (PowerShell):**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d yolo-service reid-service iep1-daemon
```

**macOS / Linux:**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d yolo-service reid-service iep1-daemon
```

> The Edge Agent (`edge_agent_dev`) requires a valid kubeconfig to init the k3s
> API client. On dev machines without k3s, start it only if you need to test the
> gRPC stream to EEP: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile edge up -d edge_agent_dev`

### 6. Open the web UI

There are **two ways** to run the frontend, and they are **not equivalent** — pick
based on what you're doing:

| Method | URL | Build | Dev-only screens (`/dev/vision`, `/dev/e2e`) |
|---|---|---|---|
| **A. Docker `frontend` service** | http://localhost:3000 | production (`vite build`) | **stripped out** — not available |
| **B. Vite dev server** (`npm run dev`) | http://localhost:5173 | development | **available** |

The dev-only screens are gated behind `import.meta.env.DEV`, which is dead code in
a production build. So the Docker frontend on `:3000` shows the normal app but
**never** the dev pipeline screens.

**A — Docker frontend (production build, no Node.js needed):**

Already running if you started the `frontend` service. Open **http://localhost:3000**.
Use this to exercise the production build or the normal onboarding/app flow.

**B — Vite dev server (required for the dev pipeline screens):**

```bash
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

Use this when you need:
- **`/store/<slug>/dev/e2e`** — the end-to-end IEP1→IEP2→IEP3 split-screen tester
  (CPU/GPU toggle, live feeds, per-camera tracking tables, IEP3 output, replay).
- **`/store/<slug>/dev/vision`** — the single-camera vision debug console.
- Hot-reload while editing frontend code.

API docs (either method): **http://localhost:8000/docs**.

> **Which to use?** Day-to-day pipeline testing → **Vite `:5173`** (it has the dev
> screens). Verifying the shippable production bundle or the plain app → **Docker
> `:3000`**. Both talk to the same backend on `:8000`.

### 6b. (Dev pipeline only) RTSP stream simulator

The `/dev/e2e` tester drives the real pipeline from the stream URLs in store config.
For dev without physical cameras you can either point cameras at a **file path**
(`/workspace/testing-data/<clip>.mp4`, mounted into `iep1-daemon`) or at the bundled
**RTSP simulator** (mediamtx + ffmpeg looping the test clips):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d \
  rtsp-server rtsp-cam1 rtsp-cam2
# Camera 1 URL: rtsp://rtsp-server:8554/cam1
# Camera 2 URL: rtsp://rtsp-server:8554/cam2
```

IEP1 samples either source at `target_fps` (stride-based for files), so both behave
the same downstream. Pressing **Start** on `/dev/e2e` resets all track tables and
restarts IEP1/IEP2/IEP3 fresh from frame 1.

---

## Running inference on a GPU (NVIDIA)

The detector + ReID run on CPU by default. To run them on an **NVIDIA GPU**, follow
this section top to bottom — it covers everything, including installing the driver
and the NVIDIA Container Toolkit. Do every step in order; don't skip the verifies.

> **Scope:** NVIDIA GPUs only, on **Linux** or **Windows 11 + WSL2 (Docker Desktop)**.
> An **Intel** GPU cannot be used this way — Docker Desktop's WSL2 VM does not pass an
> Intel GPU to Linux containers, and there is no `--gpus` equivalent for Intel. On
> Intel you would need a native Linux host with `/dev/dri` + OpenVINO (not covered here).
> You do **not** need to install the CUDA Toolkit on the host — the container's PyTorch
> wheel bundles the CUDA runtime. You only need the **NVIDIA driver** + **Container Toolkit**.

### Step G1 — Check if your GPU is already usable from Docker

Run this first. If it prints a table with your GPU, **skip to Step G4**:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

If it errors, do Step G2 (driver) and Step G3 (toolkit) for your OS.

### Step G2 — Install the NVIDIA driver

**Linux (Ubuntu/Debian):**
```bash
nvidia-smi  # if this already lists your GPU, the driver is installed — skip to G3
sudo ubuntu-drivers autoinstall   # or: sudo apt-get install -y nvidia-driver-535
sudo reboot
```

**Windows 11 + WSL2:**
1. Install the latest **NVIDIA Windows driver** (GeForce/Studio or your data-center
   driver) from nvidia.com. The Windows driver includes WSL2 GPU support.
2. **Do NOT** install an NVIDIA driver *inside* WSL — only the Windows driver.
3. Confirm in PowerShell: `nvidia-smi` (should list your GPU).

### Step G3 — Give Docker access to the GPU

**Linux — install the NVIDIA Container Toolkit:**
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**Windows 11 + WSL2 — nothing to install in WSL.** Docker Desktop ships GPU support:
1. Docker Desktop → **Settings → General →** enable **Use the WSL 2 based engine**.
2. Docker Desktop → **Settings → Resources → WSL Integration →** enable your distro.
3. Update Docker Desktop to a current version (GPU via WSL2 needs ≥ 4.x).

**Verify (both OSes)** — this must print the GPU table before continuing:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### Step G4 — Build the inference images with CUDA + start the stack

These commands **replace** the build/start commands in Quick Start steps 3–5. They add
`-f docker-compose.gpu.yml`, which builds the detector + ReID with CUDA PyTorch and
reserves the GPU for them. Run from the `retail-edge/` directory.

**Build (first time, or after pulling changes):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.gpu.yml \
  build yolo-service reid-service
```
> CUDA PyTorch is a large download (~2.5 GB) — the first build takes several minutes.
> If your NVIDIA driver is older than CUDA 12.1 (driver < 525), edit
> `docker-compose.gpu.yml` and change `cu121` to `cu118`, then rebuild.

**Start the full stack (GPU detector + ReID, everything else as usual):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.gpu.yml up -d \
  postgres pgbouncer redis minio \
  eep iep3_reconciliation live_bridge \
  yolo-service reid-service iep1-daemon
```

### Step G5 — Verify the services are on the GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.gpu.yml \
  exec yolo-service python -c "import torch; print('cuda:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
Expected: `cuda: True <your GPU name>`. Then check both services published GPU capability:
```bash
docker exec retail-edge-redis-1 redis-cli GET inference:capability:detector
docker exec retail-edge-redis-1 redis-cli GET inference:capability:reid
# both should show  "cuda": true
```

### Step G6 — Use it from the dev screen

Start the Vite frontend (Step B / `npm run dev`) and open `/store/<slug>/dev/e2e`.
The **GPU** indicator shows **available** and the CPU/GPU toggle **auto-selects GPU**.
Press **Start** — detection + ReID now run on the GPU. (You can still toggle back to
CPU per run.) On a machine with no NVIDIA GPU, the toggle stays on CPU and choosing
GPU returns "This machine has no usable GPU" — by design.

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

**Add a camera via the gRPC control socket (all camera operations go through gRPC):**
```bash
# IEP1 has no CLI args for cameras — all operations are gRPC AddCamera / RemoveCamera.
# Use a video file path as the rtsp_url for dev testing; cv2.VideoCapture accepts file paths.
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',
    request_serializer=pb2.CameraConfig.SerializeToString,
    response_deserializer=pb2.AddCameraResponse.FromString)
r = ac(pb2.CameraConfig(
    camera_id='<physical_camera_uuid>',
    rtsp_url='/workspace/testing-data/sample.mp4',
    target_fps=5.0,
    window_seconds=60.0,
    store_id='<store_uuid>',
), timeout=5.0)
print('success:', r.success, r.error)
"
```

**Verify Redis stream after one window (60 s):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec redis redis-cli XLEN stream:iep1:<physical_camera_uuid>
# > 0 means at least one manifest published
```

**Logs:**
```bash
docker compose logs -f iep1-daemon
```

---

### IEP2 Vision Worker

**What it does:** Per-camera RT-DETR → BoTSORT → resnet50_msmt17 ReID → homography → `tracking_history`. One Deployment per active camera (created by Edge Agent on k3s; one compose service in dev).

**Start with Compose (requires `CAMERA_ID`, `STORE_ID`, Redis URLs, and DB URL):**

**Windows (PowerShell):**
```powershell
$env:CAMERA_ID = "<physical_camera_uuid>"
$env:STORE_ID  = "<store_uuid>"
$env:WINDOW_SECONDS = "60"
$env:LOCAL_REDIS_URL  = "redis://redis:6379/0"
$env:SERVER_REDIS_URL = "redis://redis:6379/0"
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d iep2_vision
```

**macOS / Linux:**
```bash
CAMERA_ID=<physical_camera_uuid> \
STORE_ID=<store_uuid> \
WINDOW_SECONDS=60 \
LOCAL_REDIS_URL=redis://redis:6379/0 \
SERVER_REDIS_URL=redis://redis:6379/0 \
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d iep2_vision
```

IEP2 reads IEP1 manifests from the Redis stream for `CAMERA_ID` and processes each
frame batch through RT-DETR → BoTSORT → resnet50_msmt17 → homography → `tracking_history`.

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
docker compose --profile edge up -d iep1-daemon yolo-service reid-service edge_agent_dev
```

### Step 2 — Create a store, add cameras, configure schedules

Use the frontend at **http://localhost:3000** (onboarding wizard steps 1–9) or the API at **http://localhost:8000/docs**.

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

### Unit tests — IEP3 (no infrastructure required)

Tests run using the project `tests/` Dockerfile so the correct deps are installed:

```bash
# Build the test image (one-time)
docker build -t retailvision-tests tests/

# Run IEP3 unit tests — no postgres, redis, or any running service needed
docker run --rm -v $(pwd):/workspace -w /workspace retailvision-tests \
  pytest tests/unit/iep3/ -v
```

| Test file | What it tests | Count |
|---|---|---|
| `test_gate.py` | `cross_camera_gate` pure function (speed, NULL coords) | 8 |
| `test_matcher.py` | `ReidMatcher` cosine similarity + GlobalID linking | 6 |
| `test_selector.py` | `PositionSelector` scoring + canonical position | 5 |
| `test_state.py` | `StateManager` ACTIVE→LOST→EXITED transitions | 6 |

### Integration test — IEP3 3-camera reconciliation (requires Postgres only)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres pgbouncer
docker run --rm \
  --network retail-edge_default \
  -v $(pwd):/workspace -w /workspace \
  -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision \
  retailvision-tests pytest tests/e2e/test_iep3_reconciler.py -v -s
```

No Redis, IEP1, IEP2, or EEP needed. Test data is cleaned up via CASCADE delete.

### End-to-end pipeline test

See `docs/TESTING_GUIDE.md` Phases 3–6 for the full, platform-accurate E2E
testing procedure (UI-driven store setup → edge pipeline → accuracy validation),
with separate Windows (PowerShell) and Linux/Jetson command variants.

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
| `REID_INPUT_SOCK` | yes | ZMQ IPC socket for ReID inference |
| `TMPFS_FRAME_ROOT` | yes | Shared frame store path (reads IEP1 files) |

### IEP3 Reconciliation

| Variable | Default | Description |
|---|---|---|
| `STORE_ID` | required | Store UUID — one IEP3 instance per store |
| `WINDOW_SECONDS` | required | Must match IEP1/IEP2 |
| `DATABASE_URL_SERVER` | required | `postgresql://...` (no `+asyncpg`) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | Server Redis (reads `batch_complete` stream) |
| `REID_THRESHOLD` | `0.85` | Cosine similarity threshold |
| `MAX_SPEED_MPS` | `1.5` | Spatial gate max walking speed |
| `GRACE_SECONDS` | `300.0` | LOST → EXITED grace period |
| `EMBEDDING_DIM` | `2048` | ReID embedding dimension (resnet50_msmt17) |
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
# Image tag convention: retail-edge-{service}:latest (or a pinned digest for production)
k3s kubectl set image deployment/yolo-service \
  yolo-service=retail-edge-yolo-service:latest \
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

### Metrics & Dashboards (Prometheus + Grafana)

The stack ships with live monitoring. Prometheus scrapes a `/metrics` endpoint on
each instrumented service and the redis/postgres/node exporters; Grafana renders
provisioned dashboards from those metrics. Everything is configured from files under
[`monitoring/`](monitoring/) — no manual setup or clicking required.

**Viewing the live dashboards:**

1. From `retail-edge/`, start the stack including monitoring (the monitoring
   containers come up with the normal `up`):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
   ```
2. Open **Grafana → http://localhost:3001** (user `admin`, password from `.env`
   `GRAFANA_PASSWORD`, default `retailvision_dev`).
3. Left sidebar → **Dashboards → RetailVision** → open any of:
   - **Stream Health** — Redis stream depth (IEP1→IEP2→IEP3 flow), connected clients,
     EEP request rate.
   - **Reconciliation & Identities** — IEP3 batches, cross-camera link rate, reconcile
     p95, identity transitions.
   - **Inference Latency** — YOLO inference p50/p95, frames & detections per second,
     batch size.
4. Graphs update live while the pipeline runs. Pipeline-specific panels (stream depth,
   IEP3, YOLO) show data once cameras are streaming; EEP/Redis/host panels show data
   immediately. Use the time-range picker (top right) to zoom.

**Raw metrics & alerts (Prometheus):** **http://localhost:9090**

- `/targets` — scrape health of every service (all should be **UP**).
- `/graph` — run raw PromQL (e.g. `redis_connected_clients`, `rate(detector_frames_total[5m])`).
- `/rules` and `/alerts` — RetailVision alert rules (`NoFramesFlowing`,
  `RedisStreamBacklog`, `IEP3ReconcileSlow`, `TargetDown`). `NoFramesFlowing` fires
  when the pipeline isn't producing frames and clears automatically once it is.

Config lives in [`monitoring/prometheus.yml`](monitoring/prometheus.yml),
[`monitoring/alert_rules.yml`](monitoring/alert_rules.yml), and
[`monitoring/grafana/provisioning/`](monitoring/grafana/provisioning/).

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
               ├─ per manifest: tmpfs read → RT-DETR → BoTSORT → resnet50_msmt17 → homography
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

`local_id` is a stable UUID minted by `LocalIdentityManager` using an atomic Redis counter
(`iep2:id_counter:{camera_id}`). The `track_id → local_id` binding is stored in-process
and survives across batches within one IEP2 instance lifetime. The counter survives IEP2
restarts because it lives in Redis.
`floor_x`/`floor_y`/`zone_id` are `NULL` until a homography calibration exists.

---

## Schema

### IEP1/IEP2 tables

| Table | Key columns |
|---|---|
| `tracking_history` | `camera_id`, `local_id UUID`, `timestamp_ms BIGINT`, `floor_x/y`, `zone_id`, `bbox_confidence`, `bbox_area` |
| `local_centroids` | `local_id UUID PK`, `store_id UUID`, `centroid BYTEA` (float32[2048]) |
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

Regenerate stubs after editing `proto/agent.proto` or `proto/iep1_control.proto`:

```bash
# Runs protoc in a grpcio-tools container, applies import fixes, and touches __init__.py
bash scripts/generate_protos.sh
```

The script regenerates stubs for all three consumers (EEP, Edge Agent, IEP1) in one
pass and applies the correct package-relative import path fix for each service.
After regeneration, stage and commit the updated `*_pb2.py` / `*_pb2_grpc.py` files.

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
