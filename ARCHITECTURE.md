# RetailVision — Project Overview, Architecture & Tech Stack

> A multi-camera, edge-to-cloud retail analytics platform that tracks customers
> across overlapping and non-overlapping camera views in real time, projects them
> onto a single store floor plan, and produces one canonical trajectory per person
> for occupancy, dwell-time, and behavioural analytics.

---

## 1. The Idea

Retailers have cameras everywhere but almost no usable *understanding* of how
people move through the store. A single camera can detect and track people inside
its own frame, but the moment a customer walks from one camera's view into
another's, that camera-local track is lost and a brand-new one is created. You end
up with thousands of disconnected fragments instead of *journeys*.

**RetailVision solves the cross-camera identity problem.** It takes the raw video
feeds from every camera in a store and answers questions a single camera never
can:

- *Customer #482 entered at the front door, spent 90 s in the electronics zone,
  walked to checkout, and left* — as **one** continuous trajectory, even though
  five different cameras saw fragments of it.
- *How many distinct people are in the produce zone right now?* (occupancy)
- *What's the average dwell time per zone?* (engagement)
- *Which paths are most common between entrance and checkout?* (flow)

The hard part — and the core of the system — is **re-identification (ReID)**:
recognising that the person leaving camera A's view is the same person entering
camera B's view, then merging those two local tracks into a single **global
identity** with a coherent floor-plane path.

### Why edge + cloud?

Video is heavy and privacy-sensitive. Streaming every raw frame to the cloud is
expensive and risky. So RetailVision pushes the **heavy, per-camera computer
vision to the edge** (a device physically in the store — e.g. an NVIDIA Jetson)
and keeps only the **lightweight, cross-camera reasoning and the management/UI
plane in the cloud**. Raw frames never leave the store as a stream; only compact
detection/track metadata (and presigned thumbnail URLs for live view) cross the
network.

### Design principles

- **Edge does the pixels, cloud does the people.** Detection, tracking, and
  embedding extraction run on the edge, one isolated worker per camera. Identity
  reconciliation across cameras runs once per store in the cloud.
- **Everything is per-store and multi-tenant.** Owners onboard a store, place
  cameras and zones on a floor plan, invite staff, and configure schedules.
- **Streams, not requests, between stages.** Pipeline stages communicate through
  Redis streams with consumer groups, so each stage can crash and resume without
  losing or double-processing batches.
- **Windowed batch processing.** The pipeline works in fixed time windows
  (default **60 s**) that must be identical across IEP1/IEP2/IEP3, so the
  cross-camera reconciler can line up "what every camera saw in the same window."

---

## 2. The Pipeline at a Glance

The processing chain is a set of stages named **IEP** (Inference / Event
Processors) plus the cloud control plane **EEP** (Enterprise Event Processor).

```
Camera (RTSP / video file)
   │
   ▼
IEP1  Ingestion      decode frames → JPEG to tmpfs → 60 s window manifest → Redis
   │
   ▼
IEP2  Vision         per camera: RT-DETR detect → BoTSORT → resnet50_msmt17 ReID embedding
   │                 → homography (pixel → floor coords) → tracking_history
   │                 → publish batch_complete
   ▼
IEP3  Reconciliation cross-camera: cosine ReID match → global identities
   │                 → canonical per-person floor trajectory
   ▼
IEP4/5/6  (planned)  alerts · analytics aggregation · AI agent (NL queries)
```

| Stage | Where it runs | Cardinality | Responsibility |
|---|---|---|---|
| **IEP1 — Ingestion** | Edge | 1 daemon per device (all cameras) | Pull RTSP/video, sample at `target_fps`, write JPEG frames to tmpfs, emit a 60 s **window manifest** to edge-local Redis. |
| **IEP2 — Vision** | Edge | 1 deployment **per camera** | Read the manifest, run **RT-DETR** person detection → **BoTSORT** in-frame tracking (ReID off) → **resnet50_msmt17** ReID embeddings → **homography** projection to floor coordinates. Writes `tracking_history`, publishes `batch_complete`. |
| **IEP3 — Reconciliation** | Cloud | 1 per store | The brain. Consumes every camera's `batch_complete`, waits for all cameras in a window, then **cosine-matches embeddings across cameras** to merge local tracks into **global identities** and picks one canonical floor position per person per timestamp. Manages identity state (ACTIVE → LOST → EXITED). |
| **IEP4 — Alerts** | Cloud | planned | Rule/threshold alerts (e.g. occupancy over limit). |
| **IEP5 — Analytics** | Cloud | planned | Aggregation of global trajectories into dashboards (dwell, flow, heatmaps). |
| **IEP6 — Agent** | Cloud | planned | Natural-language analytics agent over the data. |
| **EEP** | Cloud | 1 | REST API + gRPC control plane + scheduler. The management brain. |
| **Edge Agent** | Edge | 1 per device | Thin gRPC relay: turns EEP's StartCamera/StopCamera into k3s deployments. |
| **Live Bridge** | Cloud | 1 | WebSocket relay of live frames + detections to the browser. |

### Key data concepts

- **`local_id`** — a stable identity *within one camera*, minted by IEP2 using an
  atomic Redis counter. Survives across batches and IEP2 restarts.
- **`global_id`** — a *cross-camera* identity created/maintained by IEP3 by
  linking together one or more `local_id`s that ReID believes are the same person.
- **Homography** — a per-camera calibration matrix mapping image pixels to a
  shared store floor plane (`floor_x`, `floor_y`). Until a camera is calibrated,
  floor coordinates and zone assignment are `NULL`.
- **Window** — the fixed 60 s batch boundary that aligns all cameras for
  reconciliation.

---

## 3. End-to-End Architecture

```
CLOUD (Kubernetes / Docker Compose)
┌──────────────────────────────────────────────────────────────────────┐
│  React Frontend  :3000 (prod build)  /  :5173 (Vite dev + dev screens) │
│         │ HTTP REST (/api → :8000)        │ WebSocket (live → :8010)   │
│         ▼                                  ▼                            │
│  EEP  :8000 REST  +  :50051 gRPC (TLS)   Live Bridge :8010             │
│  FastAPI · SQLAlchemy async · APScheduler · grpc.aio                   │
│   • Auth, stores, cameras, zones, calibrations, members, employees,    │
│     shifts, schedules, audit, settings                                 │
│   • Pushes StartCamera/StopCamera down the gRPC stream to edge         │
│                                                                        │
│  IEP3 Reconciliation (daemon, no port)                                 │
│   consumes stream:iep2:batch_complete → cross-camera ReID →            │
│   global_identities / global_tracking_history                          │
│                                                                        │
│  PostgreSQL + PgBouncer · Server Redis · MinIO (S3)                    │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │ gRPC TLS :50051  (edge dials OUT; stream stays open)
┌──────────────────────▼─────────────────────────────────────────────────┐
│  EDGE DEVICE (k3s / Jetson)                                            │
│                                                                        │
│  Edge Agent (systemd, thin gRPC relay)                                 │
│    StartCamera/StopCamera → k3s kubectl apply (per-camera IEP2)        │
│                                                                        │
│  IEP1 daemon (one process, all cameras)                                │
│    RTSP/video → JPEG → tmpfs → Redis XADD stream:iep1:{camera_id}      │
│                                                                        │
│  IEP2 vision (one Deployment per camera)                               │
│    XREADGROUP → RT-DETR → BoTSORT → ReID → homography →                │
│    INSERT tracking_history → XADD stream:iep2:batch_complete           │
│                                                                        │
│  YOLO service + ReID service (GPU, ZMQ unix-socket IPC)               │
│  Edge-local Redis (loopback-only, ephemeral)                           │
└──────────────────────────────────────────────────────────────────────┘
```

### Two-Redis topology (important)

The system deliberately runs **two separate Redis instances**:

| Redis | Location | Streams | Lifetime |
|---|---|---|---|
| **Edge-local** | `127.0.0.1:6379` on the edge device | `stream:iep1:{camera_id}` (IEP1 → IEP2), `iep2:id_counter:{camera_id}` | Ephemeral — bound to the store, loopback-only |
| **Server** | `redis:6379` in the cloud | `stream:iep2:batch_complete` (IEP2 → IEP3), `stream:iep2:live:{cam}` (live view) | Persistent |

This keeps high-frequency frame traffic local to the device and only sends compact
batch-complete signals across the WAN.

### The inference micro-services (YOLO / ReID)

IEP2 does not load the heavy models itself. Instead, **YOLO** (detection) and
**ReID** (resnet50_msmt17 embeddings) run as **separate GPU services** that IEP2 talks to
over **ZeroMQ unix-socket IPC** (msgpack-encoded). This lets one shared GPU
serve many per-camera IEP2 workers via batched inference, and decouples model
upgrades from the vision worker.

- `yolo_service/` — `service.py` (TensorRT engine, Jetson/GPU) and
  `service_dev.py` (CPU dev mode using Ultralytics `.pt`; supports a live
  CPU/GPU toggle via the Redis key `inference:device` and publishes hardware
  capability to `inference:capability:detector`).
- `reid_service/` — same pattern for ReID embeddings (resnet50_msmt17 via boxmot;
  2048-dim. Service is still named `reid_service` for socket/deployment continuity).

### Edge ↔ cloud control protocol (gRPC)

A single **persistent bidirectional gRPC stream** (`proto/agent.proto`). The
**edge dials out** to the cloud (so no inbound ports on the store network) and
holds the stream open:

```
Edge → Cloud:  AgentMessage   { Heartbeat | CameraStatusReport }
Cloud → Edge:  ControlMessage { StartCamera | StopCamera }
```

- The agent's **first message must be a Heartbeat**, else EEP aborts with
  `INVALID_ARGUMENT`.
- Auth is a shared secret in `x-agent-token` metadata; empty `AGENT_SECRET` =
  insecure dev mode. Production uses TLS + the shared secret (mTLS migration is
  documented in `docs/security/`).

### Reliability model

- **Stream + consumer groups** (`XREADGROUP`) let every stage resume after a
  crash without losing batches.
- IEP3 uses an **XACK-before-processing** model (see
  `docs/decisions/ADR-001-xack-before-processing.md`) and wraps each batch in a
  single asyncpg transaction, so a crash mid-batch rolls back cleanly and the
  pending-entries list stays empty.
- IEP3 runs a periodic **orphan sweep** to clean partial state left by a previous
  crashed process.

---

## 4. The Control Plane (EEP) & the Web App

**EEP** is the FastAPI service that everything management-related goes through. Its
routers map directly onto the product surface:

| Router | Purpose |
|---|---|
| `auth` | JWT login/refresh, registration, invite acceptance |
| `stores` | Create/manage stores (multi-tenant root entity) |
| `config` / `draft` | Store floor-plan config: zones, camera placement, calibration, versioned with draft → publish |
| `members` | Org members & roles (invite, edit, remove) |
| `employees` / `shifts` | Staff records, shift patterns, assignments, breaks |
| `schedules` | Per-camera active windows (days/times) that drive Start/StopCamera |
| `audit` | Audit log of privileged actions |
| `settings` | Store/org settings |
| `debug` / `dev_pipeline` | Dev-only routes (gated by `DEBUG_MODE`) to drive and inspect the pipeline |

EEP also runs the **gRPC server** that edge agents connect to and an
**APScheduler** loop that turns camera schedules into StartCamera/StopCamera
commands.

### Frontend

A **React 18 SPA** (`frontend/`) built with **Vite**, styled with **Tailwind**,
routed with **React Router v6**, talking to EEP via **Axios** (with a JWT
auto-refresh interceptor). The floor-plan editor (zone/camera placement, calibration
overlays) is built on **Konva** canvas.

- **Production build** is served by the Docker `frontend` service on `:3000`.
- The **Vite dev server** on `:5173` additionally exposes **dev pipeline screens**
  (`/store/<slug>/dev/e2e`, `/dev/vision`) that are stripped from production
  builds. These drive the real IEP1→IEP2→IEP3 pipeline with a CPU/GPU toggle,
  live feeds, per-camera tracking tables, and IEP3 output for end-to-end testing.

Key onboarding flow: a 9-step wizard places the floor plan, zones, and cameras,
then calibrates homography per camera.

---

## 5. Data Model (selected tables)

**Per-camera tracking (IEP1/IEP2):**

| Table | Key columns |
|---|---|
| `tracking_history` | `camera_id`, `local_id`, `timestamp_ms`, `floor_x/y`, `zone_id`, `bbox_confidence`, `bbox_area` |
| `local_centroids` | `local_id` PK, `store_id`, `centroid` (float32[2048] ReID embedding) |
| `camera_schedules` | active windows per camera config |
| `edge_agents` | `store_id` UNIQUE, `status`, `last_heartbeat_at`, `agent_version` |
| `camera_runtime_sessions` | start/stop bookkeeping per camera run |

**Cross-camera identity (IEP3):**

| Table | Key columns |
|---|---|
| `global_identities` | `global_id` PK, `store_id`, `state` (active/lost/exited), first/last seen, last floor pos, entry/exit zone |
| `global_local_mapping` | links `global_id` ↔ `local_id` ↔ `camera_id` (`is_active`) |
| `global_embeddings` | `(global_id, camera_id)` PK, per-camera centroid |
| `global_tracking_history` | canonical per-person floor trajectory (`batch_number`, `timestamp_ms`, `floor_x/y`, `source_camera`, `selection_score`) |

---

## 6. Tech Stack Summary

| Layer | Technology |
|---|---|
| **Frontend** | React 18, Vite, React Router v6, Konva.js (canvas), Tailwind CSS, Axios (JWT auto-refresh) |
| **API / Control plane (EEP)** | FastAPI 0.115, SQLAlchemy 2 (async), Pydantic v2, APScheduler 3.10, Alembic migrations |
| **Edge ↔ cloud comms** | gRPC (grpcio 1.64), bidirectional streaming, TLS + shared-secret auth |
| **Inter-stage messaging** | Redis 7.2 streams + consumer groups (`XREADGROUP`), two-Redis topology |
| **Computer vision** | RT-DETR (Ultralytics; TensorRT on Jetson), BoTSORT (boxmot), resnet50_msmt17 ReID (boxmot) |
| **Inference IPC** | ZeroMQ unix sockets, msgpack, batched GPU inference services |
| **Floor projection** | NumPy homography, Shapely polygons (zone hit-testing) |
| **Database** | PostgreSQL 16 + PgBouncer 1.22, asyncpg 0.29 |
| **Object storage** | MinIO (S3-compatible), boto3, presigned frame URLs |
| **Live view** | WebSocket (Live Bridge) bridging `stream:iep2:live:{cam}` → browser |
| **Edge orchestration** | k3s 1.29, Kubernetes Python client, systemd (Edge Agent) |
| **Cloud deployment** | Helm 3.14, cert-manager, external-secrets, Kubernetes |
| **Local dev** | Docker + Docker Compose (base + `dev` overlay for CPU + `gpu` overlay for CUDA) |
| **Testing** | pytest (asyncio), IEP3 unit + 3-camera integration suites, Postman collections |

### Build/runtime variants

- **`docker-compose.yml`** — base stack (YOLO/ReID build from Jetson/ARM64 bases).
- **`docker-compose.dev.yml`** — CPU-only overlay for x86 dev machines; required on
  any non-Jetson host. Swaps YOLO/ReID to CPU/GPU dev variants and enables `DEBUG_MODE`.
- **`docker-compose.gpu.yml`** — overlay that builds detector + ReID with CUDA
  PyTorch and reserves an NVIDIA GPU.

---

## 7. Repository Map

```
retail-edge/
├── docker-compose.yml / .dev.yml / .gpu.yml   # local stack + overlays
├── charts/retailvision/                       # server-side Helm chart
├── infra/
│   ├── edge/base/                             # k3s edge manifests
│   ├── pgbouncer/                             # PgBouncer config
│   └── redis-local.conf                       # edge-local Redis (loopback)
├── proto/                                     # agent.proto, iep1_control.proto
├── scripts/                                   # cert gen, edge bootstrap, proto gen
├── frontend/                                  # React 18 SPA (Vite)
├── services/
│   ├── eep/                # REST API + gRPC server + scheduler (control plane)
│   ├── edge_agent/         # thin gRPC relay → k3s
│   ├── iep1_ingestion/     # camera ingestion daemon (edge)
│   ├── iep2_vision/        # per-camera RT-DETR+BoTSORT+ReID+homography worker
│   ├── iep3_reconciliation/# cross-camera identity reconciliation (cloud)
│   ├── iep4_alerts/        # (planned) alerting
│   ├── iep5_analytics/     # (planned) analytics aggregation
│   ├── iep6_agent/         # (planned) NL analytics agent
│   ├── live_bridge/        # WebSocket live-frame relay
│   ├── yolo_service/       # YOLO/RT-DETR inference service (GPU + CPU dev)
│   └── reid_service/      # resnet50_msmt17 ReID embedding service (GPU + CPU dev)
├── docs/
│   ├── decisions/          # ADRs (e.g. ADR-001 XACK-before-processing)
│   ├── operations/         # runbooks (e.g. IEP3 orphan sweep)
│   └── security/           # mTLS migration
├── docs_models/            # model experiments (detection / tracking / reid)
└── tests/
    ├── unit/iep3/          # pure-logic IEP3 tests (no infra)
    └── e2e/                # integration + end-to-end tests
```

---

## 8. Current Status (high level)

- **Done & committed:** Auth + store shell, store config/onboarding (floor plan,
  zones, cameras, calibration, versioning), members, employees & shifts; the full
  edge→cloud vision pipeline (IEP1→IEP2→IEP3) with dev (CPU) and GPU paths.
- **In progress / planned:** Live Monitoring and Analytics frontend pages,
  IEP4 (alerts), IEP5 (analytics aggregation), IEP6 (NL agent), audit/settings UI.

For setup, run commands, environment variables, and troubleshooting, see
[`README.md`](README.md). For deeper rationale on specific decisions, see
[`docs/decisions/`](docs/decisions/).
```