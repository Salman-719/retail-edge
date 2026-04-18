# Infrastructure — DB, Docker, CI, Monitoring, K8s, Docs/Demo

**Role:** Everything cross-cutting: database migrations, containerisation, CI/CD, local orchestration, monitoring stack, AWS deployment, and the final documentation + demo package.

**Source:**
- `docker-compose.yml`
- `services/eep/migrations/`
- `monitoring/` (Prometheus + Grafana)
- `infra/` (Terraform / K8s — NEW)
- `.github/workflows/`
- `tests/`
- `README.md`, `docs/`

---

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| docker-compose (13 containers) | DONE | All services + infra |
| Dockerfiles (per service) | DONE | |
| PostgreSQL init + Alembic env | DONE | |
| Alembic migration 001, 002 | DONE | |
| Alembic migration 003 (pos_transactions) | DONE | |
| Alembic migration 004 (alert_rules, api_keys) | NOT STARTED | Blocked until M4/M8 |
| GitHub Actions CI — tests + build | DONE | `.github/workflows/ci.yml` |
| GitHub Actions — Python lint (flake8 + black) | DONE | added in M1 |
| GitHub Actions — ESLint for frontend | NOT STARTED | M1/M9 |
| Prometheus + Grafana + cAdvisor containers | DONE | |
| Prometheus scrape targets for EEP/IEP1/IEP2 | DONE | |
| Scrape targets for IEP3/4/5 | NOT STARTED | M8 |
| Grafana dashboards (6 JSON files) | NOT STARTED | M8 |
| NVIDIA GPU passthrough for IEP2 | DONE (commented on macOS, active on Linux) | |
| Integration test harness | PARTIAL | `tests/integration/test_onboarding_flow.py` |
| E2E test harness | NOT STARTED | M11 |
| Stress / soak tests | NOT STARTED | M11 |
| AWS infra (Terraform or manual) | NOT STARTED | M10 |
| EKS cluster (CPU + GPU node groups) | NOT STARTED | M10 |
| ECR repos (per service) | NOT STARTED | M10 |
| K8s manifests (`infra/k8s/`) | NOT STARTED | M10 |
| ALB ingress + SSL | NOT STARTED | M10 |
| CI/CD deploy workflow (`deploy.yml`) | NOT STARTED | M10 |
| Architecture / Deployment / Tradeoffs docs | NOT STARTED | M11 |
| Demo script | NOT STARTED | M11 |

---

## 1. Database & Migrations

All schema changes via **new** Alembic migrations under `services/eep/migrations/versions/`. Never edit shipped migrations.

Current state (after 003):
```
stores, floor_plans, zones, obstacles, cameras, calibrations,
tracking_results, tracking_history,
employees, shifts,
pos_transactions, analytics_results,
alerts
```

Pending additions:
- `004_alert_rules.py` — `alert_rules` (M4)
- `005_api_keys.py` — `api_keys` (M8)
- `006_redis_snapshots.py` — `redis_snapshots` (M8)
- MLflow backend DB via postgres init script (`mlflow` database + user) (M7)

---

## 2. Local Orchestration (docker-compose)

13 containers:
- `eep`, `iep1-ingestion`, `iep2-vision`, `iep3-alerts`, `iep4-analytics`, `iep5-agent`
- `postgres`, `redis`, `minio` (S3-compatible)
- `prometheus`, `grafana`, `cadvisor`
- `frontend`

**GPU:** `deploy.resources.reservations.devices` block exists for `iep2-vision`, commented for macOS. Uncomment on Linux with NVIDIA Container Toolkit.

Pending:
- Add `mlflow` service (M7).
- Add `mlflow` DB creation to `services/eep/migrations/init/*.sql` or a dedicated init script.

---

## 3. CI/CD (`.github/workflows/`)

### `ci.yml` — on PR to `development` / `production`

Current jobs:
- EEP unit tests (pytest)
- Frontend build (Vite)
- Python lint (flake8 + black) — tolerant ruleset, `continue-on-error: true` on black

Pending:
- Add `vitest run --frontend` job.
- Add `eslint frontend/src`.
- Run integration tests against ephemeral docker-compose (`docker compose up -d postgres redis minio` + `pytest tests/integration`).

### `deploy.yml` — on push to `main` (M10)

```
1. Configure AWS creds + ECR login
2. Build & push all images (`infra/scripts/build_push.sh`)
3. `aws eks update-kubeconfig`
4. `kubectl apply -f infra/k8s/ --recursive`
5. Wait for rollout; E2E smoke (`curl $EEP_URL/health`)
6. Rollback on failure (`kubectl rollout undo`)
```

---

## 4. Monitoring Stack (M8 focus)

### 4.1 Prometheus (`monitoring/prometheus.yml`)

Active: `eep`, `iep1-ingestion`, `iep2-vision`, cAdvisor.
Pending: enable scrape jobs for `iep3-alerts:8003`, `iep4-analytics:8004`, `iep5-agent:8005` (they need `prometheus-fastapi-instrumentator` added first).

### 4.2 Grafana dashboards (`monitoring/grafana/dashboards/`)

Six dashboards to build:
1. **System Overview** — up/down, req rate, error %, p95, cAdvisor, Redis mem, PG conns.
2. **Vision Pipeline** — active jobs, job duration, fps, detection confidence, ReID cosine, track fragmentation, GPU util.
3. **Alerts** — alerts fired (type/severity), eval latency, active rules, ack rate, time-to-ack.
4. **Analytics** — ingest rate, batch job status, heatmap duration, POS uploads, query latency.
5. **AI Agent** — queries/hour, LLM latency by provider, token usage, fallback rate, hallucination rate, tool distribution, report count.
6. **Camera Health** — per-camera quality rejection, fps, chunk status, last successful chunk.

### 4.3 Custom metrics (sources)

Each service owns its `app/core/metrics.py`. See per-IEP plan docs for the metric catalogue.

---

## 5. Kubernetes / AWS (M10)

### 5.1 AWS resources

- VPC (2 public / 2 private subnets)
- RDS PostgreSQL `db.t3.medium`
- ElastiCache Redis `cache.t3.small`
- S3 `retailvision-{env}`
- ECR repos: `retailvision-{eep,iep1-ingestion,iep2-vision,iep3-alerts,iep4-analytics,iep5-agent,frontend}`

### 5.2 EKS node groups

- CPU: `t3.large` × 3 — EEP, IEP1, IEP3-5, frontend
- GPU: `g4dn.xlarge` × 1 — IEP2 (T4 + NVIDIA device plugin)

### 5.3 Manifests (`infra/k8s/`)

```
namespace.yaml
secrets.yaml           (sealed-secrets)
configmap.yaml
{eep,iep1-ingestion,iep2-vision,iep3-alerts,iep4-analytics,iep5-agent,frontend}/
  deployment.yaml
  service.yaml
  hpa.yaml (where relevant)
ingress.yaml           (ALB: / → frontend, /api → eep, /grafana → monitoring)
monitoring/
  prometheus-values.yaml  (kube-prometheus-stack)
  grafana-values.yaml
```

Key resource requests:
- EEP: 256Mi / 250m, HPA 2–5, CPU target 70%.
- IEP2: 2Gi / 1000m + `nvidia.com/gpu: 1`, tolerations for GPU taint.

### 5.4 Ingress

AWS ALB Controller (Helm). Single `Ingress` routes:
- `/` → `frontend:3000`
- `/api` → `eep:8000`
- `/grafana` → monitoring namespace

---

## 6. Test Strategy

### Unit (`tests/unit/`)

- `test_iep_schemas.py` — DONE (all 5 IEPs)
- `test_homography.py` — edge cases (colinearity, reprojection)
- `test_quality_filters.py` — blur/dark/frozen synthetic frames
- `test_reid.py` — embedding shape, similarity monotonicity
- `test_rule_engine.py` — dwell/crowding/no-staff branches
- `test_analytics.py` — aggregation determinism
- `test_hallucination.py` — claim extraction, verification
- `test_carryover.py` — serialize/deserialize round-trip

### Integration (`tests/integration/`)

- `test_onboarding_flow.py` — DONE
- `test_iep1_pipeline.py` — upload + quality rejection
- `test_iep2_pipeline.py` — tracking job + heatmap + S3 upload
- `test_iep3_alerts.py` — rules + event + fire + persist + ack
- `test_iep4_analytics.py` — ingest + summary + POS upload + correlation
- `test_iep5_agent.py` — query + tool calls + hallucination check
- `test_eep_orchestration.py` — full chunk cycle

### E2E (`tests/e2e/`)

- `test_full_pipeline.py` — store → video → calibration → tracking → alerts → analytics → agent query. Timeout 10 min.

### Stress (`tests/stress/`)

- `test_sustained_operation.py` — 4–8 cameras × 30 min; assert stable RSS, no key explosion, analytics keep flowing.

---

## 7. Documentation (M11)

Target files in `docs/`:

| File | Contents |
|------|----------|
| `Architecture_Overview.md` | System diagram, service summaries, data flow, storage, auth, monitoring |
| `API_Documentation.md` | Swagger links per service, cross-service contracts, auth, rate limits, error shape |
| `Deployment_Guide.md` | Local (compose) + AWS + K8s + monitoring setup + troubleshooting |
| `Configuration_Guide.md` | Env vars, feature flags, tuning params, model selection, Redis TTLs |
| `Tradeoffs.md` | YOLOv8n vs v8s vs RT-DETR; ByteTrack vs BoT-SORT; micro-batch vs streaming; OSNet vs FastReID; Claude vs OpenAI; storage rationale — **with measured numbers** |
| `Demo_Script.md` | 15–20 min runbook (onboarding → live → analytics → agent → MLOps → architecture) |
| `README.md` (root) | Update with endpoints table, env vars, dev + deploy guides |

---

## 8. Demo Readiness Checklist (M11)

- [ ] 30-min sustained E2E run green
- [ ] All four dashboard sections populated with live data
- [ ] Agent answers data-grounded questions without hallucination
- [ ] One alert fires live during the checkout crowding scene
- [ ] Grafana shows vision pipeline + agent + alerts dashboards
- [ ] MLflow UI shows experiment lineage
- [ ] Tradeoffs doc carries actual numbers, not prose
- [ ] Every service healthy (`/health` = 200) during demo window

---

## Re-iteration Triggers

- Docker build cache thrashing → pin base images, split requirements layers
- CI flaky on integration → add `wait-for-it` for postgres/redis, increase health timeouts
- Grafana panels blank → verify metric names match instrumentator defaults, align panel PromQL
- K8s GPU pod stuck `Pending` → check node label `nvidia.com/gpu.present`, NVIDIA device plugin DaemonSet
- E2E flaky → identify slowest step, add retries with cap, then fix root cause
- Tradeoffs look qualitative → re-run benchmarks with fixed seeds + log to `docs/benchmarks/`
