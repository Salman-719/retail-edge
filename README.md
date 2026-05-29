# RetailVision AI

**EECE503N / EECE798N — AI Engineering Final Project**

An intelligent retail analytics platform that uses multi-camera computer vision to track customer movement, measure zone occupancy, and generate actionable insights for store managers.

---

## Overview

RetailVision AI processes video feeds from multiple ceiling-mounted cameras to produce:

- **Real-time people tracking** using YOLOv8 + ByteTrack
- **Floor-plan-anchored trajectories** via homography calibration
- **Zone occupancy analytics** (dwell time, traffic percentages)
- **Heatmap visualisations** overlaid on the store floor plan
- **AI-powered natural language insights** (Milestone 3)

The platform is structured as a microservices architecture deployed via Docker Compose, with a React frontend for store configuration and analytics dashboards.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│          (Vite · React Router · Konva · Zustand)         │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────┐
│              EEP — External Endpoint Processor           │
│                    FastAPI  ·  port 8000                 │
│   Store onboarding · Calibration · Tracking test mode   │
└──────┬───────────────────────────────────────┬──────────┘
       │ PostgreSQL                             │ S3 / MinIO
┌──────▼──────┐  ┌──────────┐  ┌──────────────▼──────────┐
│  PostgreSQL  │  │  Redis   │  │       MinIO (S3)         │
│  port 5432  │  │ port 6379│  │  port 9000 · UI: 9001    │
└─────────────┘  └──────────┘  └─────────────────────────┘

IEP Services:
  IEP1 — Data Ingestion              port 8001  (placeholder)
  IEP2 — Vision (detect/track/ReID)  per-camera CLI worker (writes to Postgres)
  IEP3 — Cross-Camera Reconciliation single-instance worker (batch-triggered)
  IEP4 — Alerts & Rules              port 8004  (placeholder)
  IEP5 — Analytics                   port 8005  (placeholder)
  IEP6 — AI Agent (LLM)              port 8006  (placeholder)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, React Router v6, Konva.js, Zustand, Tailwind CSS |
| API Gateway (EEP) | FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| Database | PostgreSQL 15 |
| Cache / Pub-Sub | Redis 7 |
| Object Storage | MinIO (S3-compatible) |
| Computer Vision | YOLOv8 (Ultralytics), ByteTrack, OpenCV |
| Migrations | Alembic |
| Containerisation | Docker, Docker Compose |
| CI | GitHub Actions |

---

## Project Structure

```
retail-edge/
├── docker-compose.yml          # Orchestrates all 8 containers
├── .env.example                # Environment variable template
├── frontend/                   # React application
│   ├── src/
│   │   ├── pages/              # Login, StoreOnboarding, LiveMonitoring, Analytics, AIAgent
│   │   ├── steps/              # 9-step onboarding wizard (Step1–Step9)
│   │   ├── components/         # Shared UI (Sidebar)
│   │   ├── api.js              # Store-scoped API client
│   │   └── store.js            # Zustand global state
├── services/
│   ├── eep/                    # External Endpoint Processor (active)
│   │   ├── app/
│   │   │   ├── api/            # REST endpoints (stores, floor_plans, zones, cameras, calibration, tracking)
│   │   │   ├── core/           # DB, Redis, S3, config
│   │   │   ├── models/         # SQLAlchemy ORM + Pydantic schemas
│   │   │   └── utils/          # homography, heatmap, tracker, pdf_utils
│   │   └── migrations/         # Alembic migrations
│   ├── iep1-ingestion/         # Placeholder
│   ├── iep2_vision/            # IEP2 vision: detect/track/local-identity + Postgres persistence
│   ├── iep3_reconciliation/    # IEP3 cross-camera reconciliation (Local ID -> Global ID)
│   ├── iep4-alerts/            # Placeholder (was iep3-alerts)
│   ├── iep5-analytics/         # Placeholder (was iep4-analytics)
│   └── iep6-agent/             # Placeholder (was iep5-agent)
├── common/                     # Shared package: config, db engine, ORM models, contracts, utils
├── tests/
│   └── unit/                   # Pydantic schema & homography unit tests
├── infra/                      # Reserved for Terraform / k8s (Milestone 3)
└── prompts/                    # Reserved for LLM prompts (Milestone 3)
```

---

## Implemented Features (Milestones 1 & 2)

### Store Onboarding Wizard (9 steps)
| Step | Description |
|---|---|
| 1 | Upload floor plan (PNG, JPG, or PDF — auto-converted) |
| 2 | Set scale & coordinate origin by marking a known real-world distance |
| 3 | Draw zones (entrance, checkout, aisle, staff-only, general) and obstacles |
| 4 | Register cameras — click their position on the floor plan |
| 5 | Upload test videos per camera |
| 6 | Mark point correspondences (camera pixel ↔ floor metre) |
| 7 | Compute homography matrix (RANSAC, reprojection error validation) |
| 8 | Save configuration to PostgreSQL + MinIO |
| 9 | Run YOLO+ByteTrack test, view live MJPEG stream, trajectory map, and zone heatmap |

### Data Persistence
- All metadata (stores, floor plans, zones, cameras, calibrations, tracking results) stored in **PostgreSQL**
- All binary files (floor plan images, videos, heatmaps) stored in **MinIO (S3)**
- No local file storage — everything is cloud-ready

---

## Prerequisites

### Required
- **Docker Desktop** — [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)  
  *(used to run PostgreSQL, Redis, and MinIO)*
- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **Node.js 18+** — [nodejs.org](https://nodejs.org/)

### Optional (for GPU-accelerated tracking)
- NVIDIA GPU with CUDA 11.8+ drivers  
  *(YOLOv8 will automatically use CPU if no GPU is available)*

---

## How to Run

### 1. Clone and configure

```bash
git clone <repo-url>
cd retail-edge
cp .env.example .env
```

The default `.env` values work out of the box for local development — no edits needed.

### 2. Start infrastructure

```bash
docker compose up -d postgres redis minio
```

This starts PostgreSQL (port 5432), Redis (port 6379), and MinIO (port 9000).  
Wait about 10 seconds for the health checks to pass, then verify:

```bash
docker compose ps
```

All three should show `healthy`.

### 3. Start the EEP backend

```bash
cd services/eep

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload --port 8000
```

On first run, the EEP automatically:
- Creates all database tables
- Creates the MinIO bucket

Interactive API docs are available at **http://localhost:8000/docs**

### 4. Start the frontend

Open a **new terminal**:

```bash
cd retail-edge/frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Using the Application

1. **Login** — Click "Enter Platform" (no credentials required in Milestone 1/2)
2. **Select or create a store** — Each store has its own isolated configuration
3. **Complete the onboarding wizard** — Steps 1–9 guide you through floor plan upload, zone definition, camera registration, and homography calibration
4. **Run a tracking test** — Step 9 processes your video with YOLO+ByteTrack and displays:
   - Live annotated MJPEG stream
   - Trajectory dots plotted on the floor plan
   - Zone-coloured occupancy heatmap
   - Per-zone dwell time table
5. **Other pages** — Live Monitoring, Analytics, and AI Agent are visible in the sidebar but marked "In Development" (active in Milestone 3)

---

## Running All Services (Full Docker Stack)

To run the EEP and all IEP placeholders in Docker instead of locally:

```bash
docker compose up --build
```

Then start only the frontend on the host:

```bash
cd frontend && npm run dev
```

> Note: The first build will take several minutes as it downloads the YOLOv8 dependencies.

---

## Running Tests

```bash
cd retail-edge

# Install test dependencies (if not already in venv)
pip install pytest opencv-python-headless numpy

# Run unit tests
pytest tests/unit/ -v
```

---

## MinIO Console

To browse uploaded files (floor plans, videos, heatmaps):

- URL: **http://localhost:9001**
- Username: `retailvision`
- Password: `retailvision_dev`

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5432/retailvision` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | MinIO endpoint |
| `S3_ACCESS_KEY` | `retailvision` | MinIO access key |
| `S3_SECRET_KEY` | `retailvision_dev` | MinIO secret key |
| `S3_BUCKET` | `retailvision` | S3 bucket name |
| `ANTHROPIC_API_KEY` | *(empty)* | For AI Agent in Milestone 3 |
| `OPENAI_API_KEY` | *(empty)* | For AI Agent in Milestone 3 |

---

## Milestone Roadmap

| Milestone | Status | Description |
|---|---|---|
| 1 | ✅ Complete | Infrastructure, microservices skeleton, DB schema, Docker Compose |
| 2 | ✅ Complete | Store onboarding pipeline, homography calibration, tracking test mode |
| 3 | 🔲 Planned | Live multi-camera pipeline (IEP1–4), real-time alerts, analytics dashboards |
| 4–6 | 🔲 Planned | AI agent, employee re-ID, advanced analytics, production hardening |
