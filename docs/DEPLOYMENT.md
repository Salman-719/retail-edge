<!--
  Rubric: S4 — Containerization and orchestration (3%), S5 — Deployment architecture and secrets (3%)
-->

# Deployment — RetailVision

## 1. Architecture diagram

```
CLOUD — AWS EKS eu-west-1 (cluster: retailvision-production, k8s v1.30)
┌─────────────────────────────────────────────────────────────────────┐
│  STATIC WORKLOADS (stable on-demand node pool, always running)       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  EEP           :8000 REST / :50051 gRPC (2 replicas, HPA 2–4) │  │
│  │  Frontend       nginx + React SPA (2 replicas, HPA 2–6)        │  │
│  │  IEP6           iep6-scheduler (1 replica) +                   │  │
│  │                 iep6-agent (KEDA-scaled, 1–8)                  │  │
│  │  PostgreSQL     TimescaleDB (StatefulSet), PgBouncer pooler     │  │
│  │  Redis          TLS-enabled (StatefulSet)                       │  │
│  │  MLflow         experiment + model registry                     │  │
│  │  Prometheus + Grafana + Alertmanager + exporters                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  DYNAMIC WORKLOADS (Karpenter Graviton SPOT; provisioned by EEP      │
│  at runtime per active store; scale to zero when store is stopped)   │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  IEP2  — one Deployment per active camera                      │  │
│  │  IEP3  — one Deployment per active store                       │  │
│  │  IEP4  — alerts daemon per store (StatefulSet)                 │  │
│  │  IEP5  — end-of-shift analytics (k8s Job, one-shot)            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  Ingress: ingress-nginx + cert-manager (Let's Encrypt TLS)           │
│  External Secrets: pulls 9 secrets from AWS Secrets Manager          │
│  app:     https://app.108.133.40.141.nip.io                          │
│  grafana: https://grafana.108.133.40.141.nip.io                      │
│  mlflow:  https://mlflow.108.133.40.141.nip.io                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │ gRPC TLS :50051 over WireGuard VPN
                             │ eep.54.247.110.0.nip.io:50051
┌────────────────────────────▼────────────────────────────────────────┐
│  EDGE DEVICE (NVIDIA Jetson + k3s; one per physical store location)  │
│  Edge Agent   systemd Restart=on-failure; dials EEP gRPC on startup  │
│  IEP1         one daemon per device; RTSP ingest → windowed manifest │
│  IEP2         one Deployment per camera (GPU inference mode)         │
│  yolo_service RT-DETR-x inference (TRT FP16 on Jetson prod)          │
│  reid_service resnet50_msmt17 ReID inference (GPU)                   │
│  Redis        edge-local, loopback-only (stream:iep1:{cam})          │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Docker images

Container registry: `ghcr.io/salman-719/retailvision/<service>:<tag>` (GHCR).
Current production tag: **1.4.0** (git tag `v1.4.0`, built by `.github/workflows/build-images.yml`).

### Cloud images (deployed by Helm chart)

| Image | Base | Purpose |
|---|---|---|
| eep | python:3.11-slim | REST API :8000 + gRPC server :50051 + APScheduler |
| frontend | node:20-alpine + nginx | React SPA; nginx proxies `/api/` → eep:8000 |
| iep3 | python:3.11-slim | Cross-camera identity reconciliation daemon |
| iep4 | python:3.11-slim | Alerts daemon (StatefulSet) |
| iep5 | python:3.11-slim | End-of-shift analytics job |
| iep6 | python:3.11-slim | AI agent (APScheduler + OpenAI) |
| mlflow | ghcr.io/…/mlflow | Experiment tracking + model registry |

### Edge images (deployed by Edge Agent onto k3s)

| Image | Base | Purpose |
|---|---|---|
| iep1 | python:3.11-slim | RTSP capture → windowed manifests → edge Redis |
| iep2 | Jetson CUDA base | RT-DETR-x detection + BoTSORT tracking + resnet50_msmt17 ReID |
| yolo_service | Jetson CUDA base | RT-DETR-x inference server (ZMQ, TRT FP16 on Jetson) |
| reid_service | Jetson CUDA base | resnet50_msmt17 ReID inference server (ZMQ, 2048-dim) |

Docker Compose variants (local dev):
- `docker-compose.yml` — base
- `docker-compose.dev.yml` — CPU-only overlay (x86 dev, no GPU required)
- `docker-compose.gpu.yml` — CUDA overlay

## 3. Secrets management

**Tool:** AWS Secrets Manager → External Secrets Operator → k8s Secret `retailvision-secrets` in namespace `retailvision`. All 9 keys land in a single Secret object mounted into pods as environment variables. No `.env` files with real secrets are in the repository; `.env.example` contains placeholder values only.

| Secret key | What it is | Consumed by |
|---|---|---|
| `DB_PASSWORD` | PostgreSQL password | EEP, IEP3, IEP4, IEP5 |
| `JWT_SECRET` | JWT signing key (HS256) | EEP |
| `GRPC_SHARED_SECRET` | gRPC mutual-auth token | EEP, Edge Agent |
| `REDIS_URL` | Redis TLS connection string (with password) | EEP, IEP3, IEP4, IEP5, IEP6 |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | MinIO / S3 object storage credentials | IEP2, EEP |
| `OPENAI_API_KEY` | OpenAI key for IEP6 AI agent | IEP6 |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin user | Grafana |
| `MLFLOW_TRACKING_URI` | MLflow server URL (in-cluster) | IEP2, MLOps scripts |

TLS certificates (gRPC channel, Redis): issued by cert-manager in-cluster (separate from Secrets Manager).

## 4. Cost estimate

Measured on AWS eu-west-1 at idle baseline (cluster up, no stores actively streaming).

| Resource | Spec | Est. monthly cost |
|---|---|---|
| EKS control plane | Fixed rate | ~$73 |
| Stable node pool | 2× t4g.large on-demand (max 4) | ~$100 |
| Network Load Balancers | ~4 NLBs (app ingress, EEP gRPC, internal postgres+redis) | ~$65 + LCU |
| EBS gp3 | Node root disks + Postgres (50 Gi) + Redis (5 Gi) PVCs | ~$20 |
| WireGuard gateway | t4g.nano EC2 | ~$3 |
| Secrets Manager + KMS + CloudWatch + DynamoDB + SQS | Control-plane logs, state lock, Karpenter spot-interruption | ~$10 |
| **Idle total** | | **~$250–350/month** |

Variable on top: Karpenter Graviton SPOT workers launch when stores activate (IEP2/3/4/5 pods) and scale back to zero when stopped. Data-transfer-out adds per active store. EIPs are free while attached.

## 5. Edge device

- **Hardware:** NVIDIA Jetson (Orin/Xavier series for production; laptop via Rancher Desktop k3s for demo — see `docs/operations/edge-laptop-setup.md`)
- **OS:** JetPack (Jetson production); Rancher Desktop k3s on Windows/Mac for laptop demo
- **Orchestration:** k3s (single-node); images pulled from GHCR; managed by Edge Agent
- **Network:** WireGuard VPN tunnel (10.99.0.0/24) between edge and cloud; Edge Agent dials EEP gRPC at `eep.54.247.110.0.nip.io:50051` over the tunnel
- **Edge Agent:** systemd service `Restart=on-failure`; re-establishes gRPC stream on restart; EEP detects reconnect and resumes camera commands automatically
- **Bootstrap:** `scripts/edge_bootstrap.sh` — installs k3s, pulls images, registers Edge Agent systemd service, configures WireGuard

## 6. How to deploy

### Cloud (Helm, production)

```bash
# Install/upgrade on EKS
helm upgrade --install retailvision charts/retailvision/ \
  -f charts/retailvision/values.production.yaml \
  -f values.cloud.yaml \
  --namespace retailvision \
  --create-namespace

# Bootstrap first super-admin after fresh install (empty DB)
kubectl exec -n retailvision deploy/eep -- \
  python -m app.cli create-admin \
  --email <admin-email> --password '<strong-password>' --name "Admin"
```

### Infrastructure (OpenTofu / Terraform)

```bash
# From infra/aws/ — provisions EKS, VPC, EIPs, IAM, EBS, S3, Secrets Manager
tofu -chdir=infra/aws init
tofu -chdir=infra/aws apply -var-file=terraform.tfvars -out eks.tfplan
tofu -chdir=infra/aws apply eks.tfplan
```

### Local dev (CPU, no GPU required)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Local GPU (edge simulation)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```
