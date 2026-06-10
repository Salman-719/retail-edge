# RetailVision Observability

Prometheus scrapes metrics from every service. Grafana visualises them. This document covers the architecture, how to access dashboards, every metric emitted by every service, and how to add new metrics.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Edge device (Jetson, k3s)                                  │
│                                                             │
│  IEP1 :9200  YOLO :9400  ReID :9401  IEP2 :9201 (per pod) │
│       └──────────┬──────────┘──────────┘                   │
│            edge Prometheus (ClusterIP, port 9090)           │
│            kubernetes_sd_configs discovers IEP2 pods        │
└──────────────────┬──────────────────────────────────────────┘
                   │  /federate  (VPN tunnel)
┌──────────────────▼──────────────────────────────────────────┐
│  Cloud (Kubernetes)                                         │
│                                                             │
│  EEP :8000  IEP3 :9300  IEP4-6 :8004-8006  Bridge :8010   │
│       └──────────┬──────────────────────────┘              │
│            cloud Prometheus (ClusterIP, no public access)   │
│                  │                                          │
│            Grafana :3000  ← publicly exposed on :3001       │
└─────────────────────────────────────────────────────────────┘
```

**Prometheus is never publicly exposed.** In docker-compose it uses `expose` (Docker-internal). In k8s/k3s it is a `ClusterIP` Service. Access it via Grafana's internal DNS, or `kubectl port-forward` for ad-hoc inspection.

**Grafana is publicly exposed** on host port 3001 (compose) / Ingress (k8s).

---

## Accessing Grafana

**Docker-compose (dev):**

```
http://localhost:3001
```

Username: `$GRAFANA_USER` (default `admin`)  
Password: `$GRAFANA_PASSWORD` — **must be set in your `.env` file, never hardcoded.**

```bash
echo "GRAFANA_PASSWORD=choose-a-strong-password" >> .env
```

**Production (k8s):** Access via your cluster's Ingress hostname. The password is sourced from the `grafana-admin` Kubernetes Secret, managed by the external-secrets operator pointing to AWS Secrets Manager.

---

## Dashboards

All dashboards are auto-provisioned from `monitoring/grafana/provisioning/dashboards/`. Grafana loads them at startup — no manual import needed.

| Dashboard | File | Description |
|-----------|------|-------------|
| RetailVision Overview | `overview.json` | All-services health, camera count, gRPC connections, pipeline throughput, ML signal summary |
| Inference Latency | `inference-latency.json` | YOLO + ReID latency, batch size, confidence distribution, embedding norms |
| Reconciliation & Identities | `reconciliation.json` | IEP3 batch times, identity transitions, ReID match rate, cosine similarity |
| Stream Health | `stream-health.json` | Redis stream depths, IEP1 frame capture/drop, IEP2 latency, BoTSORT track age, WebSocket connections |

---

## Metrics Reference

### EEP (`job="eep"`, port 8000 `/metrics`)

Auto-instrumented by `prometheus-fastapi-instrumentator`. Custom metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `eep_active_cameras` | Gauge | Number of (store, camera_config) pairs currently in the running state |
| `eep_scheduler_ticks_total` | Counter | Total APScheduler `evaluate_schedules()` invocations completed |
| `eep_grpc_connections_active` | Gauge | Number of Edge Agent gRPC streams connected right now |

HTTP metrics from instrumentator: `http_requests_total`, `http_request_duration_seconds`, `http_request_size_bytes`, `http_response_size_bytes`.

---

### IEP1 Ingestion (`job="iep1"`, port 9200 `/metrics`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `iep1_frames_captured_total` | Counter | `camera_id` | Frames written to tmpfs successfully |
| `iep1_frames_dropped_total` | Counter | `camera_id` | Frames dropped due to full inter-thread queue |
| `iep1_encode_errors_total` | Counter | `camera_id` | JPEG encoding or tmpfs write failures |
| `iep1_active_cameras` | Gauge | — | Cameras currently being captured |
| `iep1_manifest_publish_seconds` | Histogram | — | Time to XADD one window manifest to Redis |

---

### YOLO Detector (`job="detector"`, port 9400 `/metrics`)

| Metric | Type | Description |
|--------|------|-------------|
| `detector_frames_total` | Counter | Total frames processed |
| `detector_errors_total` | Counter | Frames that failed decode or caused an inference error |
| `detector_inference_seconds` | Histogram | Wall-clock time for one TRT batch inference call |
| `detector_batch_size` | Histogram | Frames per TRT batch |
| `detector_detection_confidence` | Histogram | Confidence of each accepted person detection (**ML signal**) |
| `detector_inference_confidence_mean` | Gauge | Mean confidence of all detections in the most recent batch (**drift proxy**) |

---

### ReID Embedding (`job="reid"`, port 9401 `/metrics`)

| Metric | Type | Description |
|--------|------|-------------|
| `reid_crops_processed_total` | Counter | Total person crops processed |
| `reid_errors_total` | Counter | Crops that caused inference errors |
| `reid_inference_seconds` | Histogram | Wall-clock time for one TRT ReID batch |
| `reid_batch_size` | Histogram | Crops per TRT batch |
| `reid_embedding_norm` | Histogram | L2 norm of raw 2048-dim embeddings before normalisation (**drift proxy** — collapse to near-zero signals model failure) |

---

### IEP2 Vision (`job="iep2"`, port 9201 `/metrics`)

One process per camera, discovered dynamically via `kubernetes_sd_configs` in production.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `iep2_frames_processed_total` | Counter | `camera_id` | Frames processed by this IEP2 instance |
| `iep2_frame_latency_seconds` | Histogram | `camera_id` | End-to-end time from frame receipt to DB write |
| `iep2_processing_errors_total` | Counter | `camera_id` | Unhandled errors during tracking or DB write |
| `iep2_detections_per_frame` | Histogram | `camera_id` | YOLO person detection count per frame |
| `iep2_detection_confidence` | Histogram | `camera_id` | Confidence of each detection (**ML signal / drift proxy**) |
| `iep2_track_age_frames` | Histogram | `camera_id` | Number of frames a BoTSORT track survived (**ML signal** — short tracks may signal poor detection quality) |

---

### IEP3 Reconciliation (`job="iep3"`, port 9300 `/metrics`)

| Metric | Type | Description |
|--------|------|-------------|
| `iep3_batches_processed_total` | Counter | Batches reconciled |
| `iep3_batch_reconcile_seconds` | Histogram | Per-batch reconciliation wall time |
| `iep3_identity_transitions_total` | Counter | Identity FSM transitions, by `transition` label |
| `iep3_reid_matches_total` | Counter | Successful cross-camera ReID matches |
| `iep3_reid_new_identities_total` | Counter | New GlobalIDs created |
| `iep3_batch_cameras_reporting` | Histogram | Number of cameras that reported before reconciliation fired |
| `iep3_reid_cosine_similarity` | Histogram | Cosine similarity at successful match time (**ML signal**) |
| `iep3_reid_match_rate` | Gauge | Fraction of LocalIDs matched to an existing GlobalID in the last batch (**drift proxy** — drop below 0.3 triggers alert) |

---

### IEP4 Alerts, IEP5 Analytics, IEP6 Agent (`job="iep4/5/6"`, ports 8004-8006 `/metrics`)

Auto-instrumented by `prometheus-fastapi-instrumentator`. Standard HTTP metrics: `http_requests_total`, `http_request_duration_seconds`.

---

### Live Bridge (`job="live_bridge"`, port 8010 `/metrics`)

Auto-instrumented. Custom metrics:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `live_bridge_ws_connections_active` | Gauge | `camera_id` | Active WebSocket client connections per camera |

---

## Alert Rules

Defined in `monitoring/alert_rules.yml`. Active alerts:

| Alert | Condition | Severity | Meaning |
|-------|-----------|----------|---------|
| `NoFramesFlowing` | `rate(detector_frames_total[2m]) == 0` for 2m | warning | Pipeline stalled |
| `IEP1FrameStall` | `rate(iep1_frames_captured_total[2m]) == 0` for 2m | warning | Camera RTSP stream dead |
| `RedisStreamBacklog` | `redis_stream_length > 1000` for 5m | warning | Consumer falling behind |
| `IEP3ReconcileSlow` | p95 reconcile > 10s for 5m | warning | Reconciliation bottleneck |
| `ReIDMatchRateLow` | `iep3_reid_match_rate < 0.30` for 5m | warning | ReID model regression or config issue |
| `EmbeddingNormCollapse` | p50 norm < 1.0 for 5m | **critical** | TRT ReID model failure |
| `DetectorConfidenceLow` | `detector_inference_confidence_mean < 0.35` for 5m | warning | Input distribution shift or camera obstruction |
| `TargetDown` | `up == 0` for 1m | **critical** | Any service unreachable |
| `NoEdgeAgentsConnected` | `eep_grpc_connections_active == 0` and cameras expected | **critical** | Edge Agent crashed or VPN down |

---

## Adding New Metrics

### FastAPI service (EEP, IEP4/5/6, live_bridge)

```python
from prometheus_client import Counter, Gauge, Histogram

MY_COUNTER = Counter("my_counter_total", "Description")
MY_GAUGE   = Gauge("my_gauge", "Description")
MY_HIST    = Histogram("my_histogram_seconds", "Description", buckets=[0.01, 0.1, 1.0])

# In your route or background task:
MY_COUNTER.inc()
MY_GAUGE.set(42)
MY_HIST.observe(elapsed)
```

The FastAPI instrumentator already exposes `/metrics` — no extra wiring needed.

### Daemon service (IEP1, IEP2, YOLO, ReID)

Import from the service's `metrics.py` module and call `.inc()`, `.set()`, or `.observe()`. The `start_http_server(port)` call in `main()` handles exposition.

### Adding a new service to Prometheus

1. Add a `scrape_configs` entry in `monitoring/prometheus.yml` (compose) and `monitoring/prometheus-cloud.yml` or `monitoring/prometheus-edge.yml` (production).
2. The `validate-prometheus` CI job will check the config on every push.

### Adding a Grafana panel

Edit the relevant JSON in `monitoring/grafana/provisioning/dashboards/` — Grafana picks up changes after a container restart (`docker compose restart grafana`). In production, the provisioning volume is read-only; update the ConfigMap or re-deploy.
