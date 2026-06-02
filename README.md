# RetailVision

Multi-camera retail analytics. Cameras at a store feed an edge device (Jetson)
that runs detection, tracking, and per-camera re-identification on-GPU; results
are sent to the cloud, where identities are reconciled across cameras and surfaced
in a web GUI (occupancy, dwell time, traffic, heatmaps, alerts, AI insights).

---

## Documentation

All docs live in [`docs/`](docs/README.md) and are split by purpose:

| Doc | Purpose |
|-----|---------|
| [docs/architecture-decisions.md](docs/architecture-decisions.md) | Why the system is built this way (ADRs) |
| [docs/deploy-cloud.md](docs/deploy-cloud.md) | Stand up the cloud side on AWS (CDK + k3s) |
| [docs/deploy-edge.md](docs/deploy-edge.md) | Set up a store's Jetson edge device |
| [docs/usage.md](docs/usage.md) | Operate the platform via the GUI |

Start at [docs/README.md](docs/README.md).

---

## Architecture

```
EDGE (Jetson, per store)                CLOUD (AWS, k3s on EC2)
─────────────────────────               ────────────────────────────────────
Cameras → IEP1  (ingest frames)         EEP        API gateway + GUI ingress
        → IEP2  (detect/track/ReID,     IEP3       cross-camera reconciliation
                 GPU; local Redpanda)              (one pod per store)
        → HTTPS POST tracking batch ──► Redis      batch_complete streams
                                        RDS        PostgreSQL (source of truth)
                                        Frontend   React GUI
```

- **Edge** does the GPU-heavy vision and posts results over HTTPS. No DB
  credentials or VPN on-device — just an `EEP_BASE_URL` and a shared token.
- **Cloud** persists data, reconciles identities, autoscales the API (HPA), and
  serves the GUI. See the ADRs for the reasoning behind each choice.

---

## Services

| Service | Role | Runs on |
|---------|------|---------|
| `services/iep1_ingestion` | Frame ingestion (RTSP / Test1 simulator) | Edge |
| `services/iep2_vision` | YOLO detection + tracking + ReID | Edge (GPU) |
| `services/iep3_reconciliation` | Cross-camera identity reconciliation | Cloud (per store) |
| `services/eep` | API gateway, store config, internal tracking ingest | Cloud |
| `frontend` | React GUI | Cloud |
| `common/` | Shared models, config, DB engine, contracts | Both |

---

## Local development (Docker Compose)

For development on one machine — **not** the production topology (see deploy docs
for that). Brings up Postgres, Redis, MinIO, and the services locally:

```bash
cp .env.example .env
docker compose up -d postgres redis minio   # infra
docker compose up --build                    # services
cd frontend && npm install && npm run dev    # GUI on http://localhost:5173
```

Run tests:

```bash
pip install pytest opencv-python-headless numpy
pytest tests/ -q
```

---

## Production deployment

Production runs on Kubernetes (k3s), split edge/cloud — it does **not** use
`docker-compose.yml`. Follow, in order:

1. [docs/deploy-cloud.md](docs/deploy-cloud.md) — once per environment.
2. [docs/deploy-edge.md](docs/deploy-edge.md) — once per store.
3. [docs/usage.md](docs/usage.md) — ongoing operation.
