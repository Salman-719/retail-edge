<!--
  Rubric: S4 — Containerization and orchestration (3%), S5 — Deployment architecture and secrets (3%)
-->

# Deployment — RetailVision

## 1. Architecture diagram

```
CLOUD (AWS/GCP/Azure — Kubernetes)
┌──────────────────────────────────────┐
│  EEP          :8000 REST / :50051 gRPC│
│  IEP3         (daemon, no port)       │
│  Live Bridge  :8010 WebSocket         │
│  Frontend     :3000                   │
│  PostgreSQL + PgBouncer               │
│  Redis (cloud)                        │
│  MinIO                                │
│  Prometheus + Grafana                 │
└───────────────┬──────────────────────┘
                │ gRPC TLS :50051
┌───────────────▼──────────────────────┐
│  EDGE DEVICE (k3s / Jetson)           │
│  Edge Agent (systemd)                 │
│  IEP1 (one per device)                │
│  IEP2 (one Deployment per camera)     │
│  YOLO service + OSNet service (GPU)   │
│  Redis (edge-local, loopback-only)    │
└──────────────────────────────────────┘
```

## 2. Docker images

| Image | Base | Purpose |
|---|---|---|
| eep | python:3.11-slim | REST API + gRPC server |
| iep3_reconciliation | python:3.11-slim | Cross-camera identity reconciliation |
| iep1_ingestion | python:3.11-slim (or Jetson base) | Camera ingestion daemon |
| iep2_vision | Jetson / CUDA base | YOLO + ByteTrack + ReID |
| yolo_service | Jetson / CUDA base | YOLO inference service |
| osnet_service | Jetson / CUDA base | OSNet ReID inference service |
| live_bridge | python:3.11-slim | WebSocket relay |
| frontend | node:20-alpine + nginx | React SPA |

Docker Compose variants:

- `docker-compose.yml` — base (Jetson/ARM64)
- `docker-compose.dev.yml` — CPU-only overlay for x86 dev
- `docker-compose.gpu.yml` — CUDA overlay

Kubernetes: `charts/retailvision/` Helm chart.

## 3. Secrets management

Tool: AWS Secrets Manager via external-secrets Kubernetes operator (see `charts/retailvision/`).

| Secret | What it is | Where used |
|---|---|---|
| DB_PASSWORD | PostgreSQL password | EEP, IEP3 |
| JWT_SECRET | JWT signing key | EEP |
| GRPC_SHARED_SECRET | gRPC auth token | EEP, Edge Agent |
| MINIO_ACCESS_KEY | MinIO credentials | IEP2, EEP |
| TLS_CERT / TLS_KEY | gRPC TLS certificates | EEP, Edge Agent |

What is NOT in the repository: No `.env` files with real secrets are committed. `.env.example` contains placeholder values only.

## 4. Cost estimate

| Resource | Spec | Est. monthly cost |
|---|---|---|
| Kubernetes node pool | TODO | $TODO |
| PostgreSQL | TODO | $TODO |
| Redis (cloud) | TODO | $TODO |
| MinIO / S3 | TODO | $TODO |
| Load balancer | TODO | $TODO |
| **Total** | | **$TODO** |

## 5. Edge device

- Hardware: NVIDIA Jetson TODO (model)
- OS: JetPack TODO
- Orchestration: k3s 1.29
- Edge Agent: systemd service (`/etc/systemd/system/edge-agent.service`), auto-restarts on failure
- Bootstrap: `scripts/edge_bootstrap.sh`

## 6. How to deploy

```bash
# Cloud (Helm)
helm upgrade --install retailvision charts/retailvision/ -f values.prod.yaml

# Local dev (CPU)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Local GPU
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```
