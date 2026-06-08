# Prometheus + Grafana for RetailVision — Complete Beginner's Guide

> **Audience:** someone who has *never used Prometheus or Grafana*. This guide
> explains what they are, how they fit RetailVision, exactly what metrics to expose
> for each service, how to wire the (already-present-but-empty) Prometheus/Grafana
> containers, where data is stored, how a grader views the dashboards, plus a Q&A
> mirroring the MLflow guide. It is a **planning + step-by-step implementation**
> document. **§7 is now driven by copy-paste Claude Code prompts, split into two
> phases**: **Phase 1 = Tiers 1+2** (the recommended deliverable — do this now and
> stop) and **Phase 2 = Tier 3** (production-ish extras, only if you continue after
> Phase 1 is finished). Each step gives you a prompt to run and a verify check so you
> can build the whole stack with Claude Code doing the edits and you confirming each
> result.

> **Read this alongside [`MLFLOW_GUIDE.md`](MLFLOW_GUIDE.md).** They are different
> tools: **MLflow = offline "which model is best?"** · **Prometheus+Grafana =
> online "is the running pipeline healthy *right now*?"** Same project, opposite
> halves of the lifecycle.

---

## Table of Contents

1. [What Prometheus and Grafana are (plain English)](#1-what-prometheus-and-grafana-are-plain-english)
2. [The concepts you must know](#2-the-concepts-you-must-know)
3. [How they fit RetailVision — the plan](#3-how-they-fit-retailvision--the-plan)
4. [The one hard part: your pipeline isn't all HTTP servers](#4-the-one-hard-part-your-pipeline-isnt-all-http-servers)
5. [What metrics to expose per service](#5-what-metrics-to-expose-per-service)
6. [Answering the same questions you asked about MLflow](#6-answering-the-same-questions-you-asked-about-mlflow)
7. [Step-by-step implementation (Phase 1 = Tiers 1+2, Phase 2 = Tier 3)](#7-step-by-step-implementation)
8. [The instrumentation code (copy-paste)](#8-the-instrumentation-code-copy-paste)
9. [PromQL — the query language you need](#9-promql--the-query-language-you-need)
10. [Building dashboards & how the grader views them](#10-building-dashboards--how-the-grader-views-them)
11. [Are you overdoing it? Scope by time budget](#11-are-you-overdoing-it-scope-by-time-budget)
12. [The minimal "enough" metric set](#12-the-minimal-enough-metric-set)
13. [Everything you should know to actually use them](#13-everything-you-should-know-to-actually-use-them)
14. [Common mistakes & how to avoid them](#14-common-mistakes--how-to-avoid-them)
15. [Glossary & FAQ](#15-glossary--faq)
16. [Final recommendation](#16-final-recommendation)

---

## 1. What Prometheus and Grafana are (plain English)

- **Prometheus** is a **time-series database that pulls numbers from your services
  on a timer.** Every N seconds it makes an HTTP GET to a `/metrics` URL on each
  service, reads a list of numbers ("scrapes" them), timestamps them, and stores
  them. It also has a query language (**PromQL**) to ask questions like "how many
  frames per second is camera 3 processing, averaged over the last 5 minutes?"

- **Grafana** is the **dashboard layer**. It connects to Prometheus as a *data
  source*, runs PromQL queries, and draws graphs, gauges, and tables you arrange on
  dashboards. It's the pretty front-end; Prometheus is the engine.

```
your services expose /metrics  ──Prometheus scrapes every 15s──►  Prometheus (stores TSDB)
                                                                        │
                                                              Grafana queries via PromQL
                                                                        │
                                                                   Dashboards (browser)
```

**The key mental shift from MLflow:** with MLflow *you* call `log_metric(...)` once
per experiment run. With Prometheus, your service just **exposes a live `/metrics`
page**, and Prometheus **comes and reads it automatically, forever.** You never
"send" metrics — you *publish* them and Prometheus *pulls*. This is the "pull
model," and it's the single most important idea to internalize.

---

## 2. The concepts you must know

| Concept | What it is | RetailVision example |
|---|---|---|
| **Exporter / `/metrics` endpoint** | An HTTP page each service serves, listing its current metric values in a plain-text format | `eep:8000/metrics`, `iep3:9300/metrics` |
| **Scrape** | Prometheus's timed HTTP GET of a `/metrics` page | every 15s Prometheus reads each service |
| **Target** | One thing Prometheus scrapes (a service:port) | `eep`, `iep3`, `redis_exporter` |
| **Job** | A named group of targets in `prometheus.yml` | job `eep`, job `pipeline` |
| **Metric** | A named number, optionally with labels | `frames_processed_total{camera="cam1"}` |
| **Labels** | Key/value tags that split a metric into series | `camera="cam1"`, `stage="yolo"` |
| **Datasource** (Grafana) | The connection Grafana uses to query Prometheus | "Prometheus @ http://prometheus:9090" |
| **Panel / Dashboard** (Grafana) | One graph / a page of graphs | "Pipeline Throughput" dashboard |

### The four metric *types* (you only need these)
| Type | Meaning | Use for | Example |
|---|---|---|---|
| **Counter** | Only ever goes up (reset on restart) | totals / rates | `frames_processed_total` |
| **Gauge** | Goes up and down | current state | `active_global_identities` |
| **Histogram** | Buckets of observations → percentiles | latencies/sizes | `detector_inference_seconds` |
| **Summary** | Like histogram, client-side quantiles | rarely needed here | — |

**Rule of thumb:** *counts of things that happened* → Counter. *A current value* →
Gauge. *How long something took / how big it was* → Histogram.

---

## 3. How they fit RetailVision — the plan

You already have **empty** Prometheus and Grafana containers in
`docker-compose.yml` (ports 9090 and 3001) — but they do nothing because:
- there is **no `prometheus.yml`** telling Prometheus what to scrape,
- **no service exposes `/metrics`**,
- Grafana has **no datasource and no dashboards** provisioned.

The plan fills those three gaps:

```
EEP        :8000/metrics   (FastAPI — easy)        ─┐
Live Bridge:8010/metrics   (FastAPI — easy)        ─┤
IEP3       :9300/metrics   (daemon — add a thread) ─┼─► Prometheus :9090 ─► Grafana :3001
Detector   :9400/metrics   (add metrics thread)    ─┤      (scrape 15s)      (dashboards)
ReID svc   :9401/metrics   (add metrics thread)    ─┤
redis_exporter :9121       (ready-made container)  ─┘
```

What you'll create:
- a **`monitoring/`** directory holding `prometheus.yml` and Grafana provisioning
  (datasource YAML + dashboard JSONs),
- **`/metrics`** on the cloud-side services,
- a **`redis_exporter`** container (gives stream/lag metrics with *zero* code).

**Deliberate scope choice:** instrument the **cloud-side** services (EEP, Live
Bridge, IEP3) + Redis. **Skip the edge daemons (IEP1, IEP2)** for the demo — see §4
for why, and §11 for the trade-off.

---

## 4. The one hard part: your pipeline isn't all HTTP servers

This is the section that makes or breaks the setup, and it's specific to your
architecture. Services fall into three groups:

### Group A — already web servers (trivial) ✅
**EEP** and **Live Bridge** are FastAPI apps. Adding `/metrics` is a 2-line library
call (`prometheus-fastapi-instrumentator`). You get request rate, latency, and
error counts for free, plus you can add custom metrics.

### Group B — have a server thread but aren't web apps (easy) ✅
The **detector service** (`yolo-service` container, runs RT-DETR-x/YOLO11n) and the
**ReID service** (`reid-service` container, resnet50_msmt17) already run a gRPC
**health server** in a thread (you saw this in `yolo_service/service_dev.py`). You add
a tiny `prometheus_client.start_http_server(9400)` call alongside it — now they expose
`/metrics` on a side port. Perfect place to log inference latency and batch size.

### Group C — portless daemons (needs a decision) ⚠️
**IEP1, IEP2, IEP3** are background consumers with **no HTTP server at all.** Two
patterns exist:

1. **Pull (add a metrics server):** call `start_http_server(port)` inside the
   daemon so Prometheus can scrape it. Works great for **IEP3** (one instance,
   cloud-side, reachable).
2. **Push (Pushgateway):** the daemon *pushes* metrics to a **Prometheus
   Pushgateway**, which Prometheus then scrapes. Needed for **edge** daemons
   because of the network problem below.

### Why edge instrumentation is hard (and why we skip it for the demo)
- **IEP2 is one pod per camera** on the **edge device** (k3s/Jetson), often behind
  NAT. Cloud Prometheus generally **cannot reach** edge pods to scrape them.
- IEP2 pods are **ephemeral** (created/destroyed per camera by the Edge Agent) —
  scrape targets that come and go are awkward for the pull model.
- The "correct" production answer is a **cloud Pushgateway** the edge pushes to, or
  a small **edge-side Prometheus** that uses `remote_write` to the cloud. Both add
  real complexity for little demo value.

**Decision for this project:** instrument **Group A + Group B + IEP3 (pull)** and
**add `redis_exporter`**. That covers throughput, latency, identities, and stream
health end-to-end — a complete story — **without** the edge networking rabbit hole.
Mention the Pushgateway/remote_write path in your write-up as "how we'd scale to
the edge." (See §11 for the explicit cut line.)

---

## 5. What metrics to expose per service

These map to your pipeline's real failure modes. Names follow Prometheus
conventions (`_total` for counters, base unit `_seconds`/`_bytes`, labels in `{}`).

### 5.1 EEP (FastAPI, cloud) — `:8000/metrics`
**Free (from the instrumentator):**
- `http_requests_total{handler,method,status}` — request volume & error rate
- `http_request_duration_seconds` (histogram) — API latency

**Custom (worth adding):**
- `eep_grpc_commands_total{type="start|stop"}` — Start/StopCamera sent to edge
- `eep_connected_edge_agents` (gauge) — agents currently streaming
- `eep_scheduler_ticks_total` — APScheduler firing

### 5.2 Live Bridge (FastAPI, cloud) — `:8010/metrics`
- `http_request_duration_seconds` (free)
- `live_bridge_active_connections{camera}` (gauge) — WebSocket clients per camera
- `live_bridge_frames_relayed_total{camera}` (counter)
- `live_bridge_presign_seconds` (histogram) — S3 presign latency

### 5.3 IEP3 Reconciliation (daemon, cloud) — `:9300/metrics` ⭐ the high-value one
This is your "brain" — its metrics show whether cross-camera identity actually works.
- `iep3_batches_processed_total` (counter)
- `iep3_batch_reconcile_seconds` (histogram) — time to reconcile one batch
- `iep3_reid_matches_total` vs `iep3_reid_new_identities_total` — **cross-camera
  link rate** = matches / (matches + new). The single most informative ratio.
- `iep3_global_identities{state="active|lost|exited"}` (gauge)
- `iep3_coordinator_wait_seconds` (histogram) — how long it waits for all cameras
- `iep3_partial_batch_timeouts_total` (counter) — cameras missing from a window

### 5.4 Detector service (GPU/CPU, edge or cloud) — `:9400/metrics`
> The detector is **RT-DETR-x** (`rtdetr-x.pt`) in production; dev uses a lighter
> **YOLO11n** stand-in. Metrics are named `detector_*` (not `yolo_*`) so they're
> accurate regardless of model. The compose **service name is still `yolo-service`**,
> but the Prometheus **job is `detector`**.
- `detector_inference_seconds` (histogram) — detection latency per batch
- `detector_batch_size` (histogram) — your `_collect_batch` varies 1..MAX
- `detector_frames_total` / `detector_detections_total` (counters)
- `detector_info{model="rtdetr-x.pt|yolo11n.pt"}` (gauge=1) — which model is loaded

### 5.5 ReID service (GPU/CPU) — `:9401/metrics`
> The ReID model is **resnet50_msmt17** (2048-dim), served by the **`reid-service`**
> container. (Some older docs call this "OSNet/512-dim" — that's stale; the running
> service is resnet50.) Metrics are named `reid_*`.
- `reid_embedding_seconds` (histogram) — embedding extraction latency
- `reid_batch_size` (histogram)
- `reid_embeddings_total` (counter)

### 5.6 Redis (via `redis_exporter`, zero code) — `:9121/metrics` ⭐ cheapest win
The exporter exposes dozens of metrics automatically; the ones that matter to you:
- `redis_stream_length{stream}` — depth of `stream:iep1:*` and
  `stream:iep2:batch_complete`. **Rising depth = a stage is falling behind.**
- consumer-group lag / pending entries (the exporter exposes XINFO-derived metrics)
- `redis_connected_clients`, `redis_memory_used_bytes`

> **Stream depth + lag is the most project-relevant dashboard you can build** — it
> directly visualizes the IEP1→IEP2→IEP3 flow and catches the silent failure mode
> (a stage stalling) that nothing else shows. And it costs you *no code*.

### 5.7 Infra extras (optional, ready-made exporters)
- `postgres_exporter` → connections, slow queries, table sizes.
- `node_exporter` / `cAdvisor` → host CPU/RAM, per-container resource usage.
- Add these only if you want an "infrastructure health" dashboard.

---

## 6. Answering the same questions you asked about MLflow

### 6.1 Should Prometheus and Grafana be in separate containers?
**Yes — and they already are.** Prometheus and Grafana are **two separate
containers** (they're independent programs), and they're **already defined** in your
`docker-compose.yml` (just empty). This differs slightly from MLflow:

- **MLflow:** *one* server container + your eval script as the client.
- **Prometheus + Grafana:** **two** containers — one for the database/scraper
  (Prometheus), one for the dashboards (Grafana) — **plus** the "clients" are your
  own services exposing `/metrics` (not a separate script). Optionally a third/fourth
  container for **exporters** (`redis_exporter`, etc.).

So a typical stack is: `prometheus` + `grafana` + `redis_exporter` = 3 containers,
and your existing services each grow a `/metrics` endpoint (no new container for
those). **Never run Prometheus and Grafana in one container** — they're distinct
images with distinct jobs; keep them separate (the standard pattern).

### 6.2 Are they related to Kubernetes?
**Not required — Docker Compose is enough for this project.** But unlike MLflow,
Prometheus has a *strong* k8s story you should be aware of:
- In production, the **kube-prometheus-stack** Helm chart auto-discovers pods and
  scrapes them — this is how you'd eventually monitor edge IEP2 pods on k3s.
- For your demo: **plain Compose, no k8s.** If you later add monitoring to
  `charts/retailvision/`, you'd use ServiceMonitors / the prometheus-operator — out
  of scope here.
- Don't conflate: your **edge runs k3s** for IEP2; Prometheus/Grafana run as
  **cloud-side Compose containers** and scrape the cloud services. Keep them mentally
  separate, exactly as with MLflow.

### 6.3 How do I "log", where does data go, where does the grader see it?
The wording differs from MLflow because of the pull model:

**How do I "log"?** You **don't call a log function per event.** Instead you:
1. define metric objects once (`Counter(...)`, `Histogram(...)`),
2. update them inline in your code (`.inc()`, `.observe(seconds)`, `.set(value)`),
3. expose them on `/metrics` (one library call).
Prometheus then pulls them on its own schedule.

**Where does the data physically go?**
| What | Goes to |
|---|---|
| The raw time-series numbers | **Prometheus' own TSDB** (a Docker volume) — *not* Postgres |
| Dashboard definitions, users, settings | **Grafana's DB** (its `grafana_data` volume, SQLite by default) |
Note: unlike MLflow, **Prometheus does *not* use your Postgres or MinIO.** It has
its own storage. By default Prometheus keeps ~15 days of history (configurable).

**Where does the grader see results?** In **Grafana at http://localhost:3001**
(login from `GRAFANA_USER`/`GRAFANA_PASSWORD`). They open a provisioned dashboard
and watch live graphs. They can *also* open **Prometheus at http://localhost:9090**
to run raw PromQL, but Grafana is the intended view. Because dashboards are
**provisioned from files** (§7), they appear automatically — the grader doesn't have
to build anything.

---

## 7. Step-by-step implementation

> Goal: make the existing empty containers actually scrape your services and show
> dashboards.

> **The plan is split into two phases — stop after Phase 1.**
>
> | Phase | Covers | Effort | When |
> |---|---|---|---|
> | **Phase 1** | **Tier 1 + Tier 2** (§11): prometheus.yml, redis_exporter, EEP, **IEP3 (the brain)**, a YOLO latency panel, 3 dashboards, **postgres + node exporters**, and **alerting rules** | ~1–1.5 days | Do this now. It's the complete, recommended deliverable. |
> | **Phase 2** | **Tier 3** (§11): the remaining service instrumentation (Live Bridge + ReID service) and the **edge push model** (Pushgateway/remote_write) | +1 day | **Only if you decide to continue after Phase 1 is finished and verified.** Phase 2 picks up *exactly* where Phase 1 left off — same `monitoring/` dir, same running stack. |
>
> **How to use this section with Claude Code.** Each step has a 📋 **Claude Code
> prompt** (copy-paste it into Claude Code from the `retail-edge/` directory) and a
> ✅ **Expect / verify** block telling you what success looks like and the exact
> command or URL to confirm it. Work the steps in order — later steps assume the
> files and containers from earlier ones exist. After every prompt, *actually run the
> verify check before moving on*; don't trust "it should work." If a check fails,
> paste the failing output back to Claude Code and ask it to diagnose.
>
> **General tips for these prompts:**
> - Always tell Claude Code which directory you're in (it's `retail-edge/`).
> - Ask it to **show you a diff before applying** if you want to review changes:
>   add *"show me the change before writing it"* to any prompt.
> - When something is DOWN/broken, the best follow-up prompt is literally:
>   *"Here is the output of `<command>`: <paste>. Why is `<target>` failing and how
>   do I fix it?"*

---

# PHASE 1 — Tiers 1 + 2 (do this now) ⭐

> **Outcome of Phase 1:** Prometheus scraping Redis + EEP + IEP3 (and optionally
> YOLO) + Postgres + the host, Grafana auto-loading **3 dashboards** (Stream Health,
> Reconciliation & Identities, Inference Latency), **alerting rules** that fire on a
> stalled pipeline, and a README section for the grader. This is the recommended
> stopping point — it tells the full RetailVision story cloud-side with no edge
> complexity. **Estimated effort: ~1–1.5 days.**
>
> **Tier 1 is reached at the end of Step 5a + Step 7** (Stream Health dashboard live).
> **Tier 2 is reached at the end of Step 7** (IEP3 + YOLO dashboards live).
> **Steps 9–10 (infra exporters + alerting)** round Phase 1 out to a polished,
> alert-capable deliverable.

### Step 0 — Prerequisites
- Stack builds and runs.
- Scope for Phase 1: EEP + IEP3 + redis_exporter (+ optional YOLO) + postgres/node
  exporters + alerting rules. Live Bridge, the ReID service, and the edge push model are
  **deferred to Phase 2**.

📋 **Claude Code prompt — orient yourself first:**
```
Read docker-compose.yml and docker-compose.dev.yml in retail-edge/. List every
service, the ports it exposes, and confirm whether `prometheus`, `grafana`, and
`redis` services already exist and what (if anything) they currently mount. Also
tell me the exact service names for EEP, Live Bridge, IEP3, the detector
(yolo-service), the ReID service (reid-service), and Redis as written in the compose
files — I need them for prometheus.yml.
```
✅ **Expect / verify:** Claude lists the services and gives you the *exact* compose
service names (e.g. `eep`, `live_bridge`, `iep3_reconciliation`, `redis`). **Write
these down** — the `prometheus.yml` targets in Step 1 must match them character-for-
character. If the names Claude reports differ from the examples in this guide, trust
Claude's report (it read your real files) and adjust the later prompts accordingly.

### Step 1 — Create the `monitoring/` directory and `prometheus.yml`
This is the missing file that makes Prometheus do anything.

📋 **Claude Code prompt:**
```
Create retail-edge/monitoring/prometheus.yml with a 15s global scrape_interval and
one scrape job per target, using the Docker Compose SERVICE NAMES (not localhost)
you found in Step 0. Targets:
  - prometheus itself  (localhost:9090)
  - eep                (<eep-service-name>:8000)
  - live_bridge        (<live-bridge-service-name>:8010)
  - iep3               (<iep3-service-name>:9300)
  - detector           (yolo-service:9400)   # job "detector", host yolo-service
  - reid               (reid-service:9401)
  - redis              (redis_exporter:9121)
Use the exact service names from the compose files. Add a short comment on each job.
```
This should produce something equivalent to:
```yaml
global:
  scrape_interval: 15s          # how often to pull every target

scrape_configs:
  - job_name: prometheus        # Prometheus scraping itself (sanity)
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: eep
    static_configs:
      - targets: ["eep:8000"]

  - job_name: live_bridge
    static_configs:
      - targets: ["live_bridge:8010"]

  - job_name: iep3
    static_configs:
      - targets: ["iep3_reconciliation:9300"]

  - job_name: detector              # host is yolo-service; model is RT-DETR-x/YOLO11n
    static_configs:
      - targets: ["yolo-service:9400"]

  - job_name: reid
    static_configs:
      - targets: ["reid-service:9401"]

  - job_name: redis
    static_configs:
      - targets: ["redis_exporter:9121"]
```
> Targets use **Docker Compose service names** (`eep`, not `localhost`) because
> Prometheus scrapes them over the Compose network.

✅ **Expect / verify:** The file `retail-edge/monitoring/prometheus.yml` exists with
one job per target. Quick sanity check — ask Claude *"validate the YAML syntax of
monitoring/prometheus.yml and confirm every target uses a real compose service name
from Step 0."* It should be valid YAML and the service names should match. (Don't
start anything yet — that's Step 4.)

### Step 2 — Mount the config + add redis_exporter to Compose
The `prometheus` container needs the config file mounted, plus a persistence volume,
and you need the `redis_exporter` container.

📋 **Claude Code prompt:**
```
In retail-edge/, edit the existing `prometheus` service in docker-compose.yml to:
  - mount ./monitoring/prometheus.yml to /etc/prometheus/prometheus.yml:ro
  - add a named volume prometheus_data mounted at /prometheus for persistence
  - set restart: unless-stopped
Then add a new `redis_exporter` service (image oliver006/redis_exporter:v1.62.0)
pointing REDIS_ADDR at redis://redis:6379, exposing port 9121, depends_on redis.
Finally add `prometheus_data:` under the top-level volumes: block.
Show me the resulting diff for both the prometheus service and the new service.
```
The result should look like:
```yaml
  prometheus:
    image: prom/prometheus:v2.51.0
    ports: ["9090:9090"]
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus            # persistence (add to volumes:)
    restart: unless-stopped

  redis_exporter:
    image: oliver006/redis_exporter:v1.62.0
    environment:
      REDIS_ADDR: "redis://redis:6379"
    ports: ["9121:9121"]
    depends_on: [redis]
    restart: unless-stopped
```
Add `prometheus_data:` under the top-level `volumes:` block.

✅ **Expect / verify:** Ask Claude *"run `docker compose config` from retail-edge/ and
show me only the prometheus and redis_exporter sections."* The command must succeed
(it fails loudly on a YAML/indentation error) and the rendered output should show the
volume mount and the new exporter. If `docker compose config` errors, paste the error
back to Claude — it's almost always an indentation mistake in the compose file.

### Step 3 — Provision Grafana (datasource + dashboards from files)
So dashboards exist on startup (not hand-clicked).

📋 **Claude Code prompt:**
```
In retail-edge/, set up Grafana provisioning:
1. Create monitoring/grafana/provisioning/datasources/prometheus.yml defining a
   Prometheus datasource (type prometheus, access proxy, url http://prometheus:9090,
   isDefault true).
2. Create monitoring/grafana/provisioning/dashboards/dashboards.yml with a file
   provider named RetailVision, folder RetailVision, path
   /etc/grafana/provisioning/dashboards.
3. Edit the existing `grafana` service in docker-compose.yml to mount
   grafana_data:/var/lib/grafana and
   ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
   without removing any existing grafana settings (env vars, ports). Show me the
   grafana service diff.
```
The two provisioning files should match:

`monitoring/grafana/provisioning/datasources/prometheus.yml`:
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

`monitoring/grafana/provisioning/dashboards/dashboards.yml`:
```yaml
apiVersion: 1
providers:
  - name: RetailVision
    folder: RetailVision
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```
Mounted into the Grafana service:
```yaml
  grafana:
    # ...existing...
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
```
Put your dashboard JSON files (exported from the UI later, see §10) in the
`dashboards/` folder.

✅ **Expect / verify:** Both provisioning files exist and `docker compose config`
still succeeds (verify the grafana volumes appear and its existing env/ports are
*intact* — provisioning should be additive, not a rewrite). You'll confirm the
datasource actually loads in Step 4.

### Step 4 — Bring up monitoring & verify Prometheus sees targets
📋 **Claude Code prompt:**
```
From retail-edge/, start only the monitoring stack:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d prometheus grafana redis_exporter
Then show me `docker compose ps` for those three, and curl
http://localhost:9090/api/v1/targets and summarize which targets are UP vs DOWN.
```
✅ **Expect / verify:**
- `docker compose ps` shows `prometheus`, `grafana`, `redis_exporter` all **running**
  (not restarting — a restarting prometheus usually means a bad `prometheus.yml`;
  check with `docker compose logs prometheus`).
- Open **http://localhost:9090/targets** in a browser. **`prometheus` and `redis`
  are UP.** The app services (`eep`, `live_bridge`, `iep3`, `detector`, `reid`) are
  **DOWN** — *this is expected*, they don't expose `/metrics` until Step 5.
- Open **http://localhost:3001** → log in (user `admin`, password from `.env`
  `GRAFANA_PASSWORD`) → **Connections → Data sources** → you should see **Prometheus**
  already there (proves Step 3 provisioning worked). Click **Test** — it should say
  the datasource is working.

### Step 5a — Instrument EEP (Tier 1 — the easy FastAPI win)
Add `/metrics` to EEP. The reference code is in §8.1.

📋 **Claude Code prompt (EEP only — Live Bridge is deferred to Phase 2):**
```
EEP is a FastAPI app in retail-edge/. Do exactly this:
1. Add `prometheus-fastapi-instrumentator` and `prometheus-client` to EEP's
   requirements.txt.
2. In EEP's FastAPI app file, right after the `app = FastAPI(...)` line, add:
       from prometheus_fastapi_instrumentator import Instrumentator
       Instrumentator().instrument(app).expose(app)
   so it serves GET /metrics.
Find the correct app file (don't guess — locate where FastAPI() is instantiated).
Show me the edits, then rebuild and restart just eep.
```
✅ **Expect / verify (EEP):**
1. **Endpoint:** `docker compose exec eep curl -s localhost:8000/metrics | head` →
   plain-text `# HELP` / `# TYPE` lines. Connection-refused → check
   `docker compose logs eep`.
2. **Prometheus:** http://localhost:9090/targets → `eep` flips **DOWN → UP** within
   one 15s scrape.
3. **Data:** http://localhost:9090/graph → query `http_requests_total` → hit a few
   EEP endpoints → the value climbs.

> ✅ **Tier 1 milestone:** once you also build the Stream Health dashboard in Step 7,
> you have the full minimum-viable chain (pull → store → visualize). Everything after
> this in Phase 1 is Tier 2.

### Step 5b — Instrument IEP3 (Tier 2 — the brain ⭐)
Add `/metrics` to the IEP3 daemon. The reference code is in §8.2.

📋 **Claude Code prompt (IEP3, the portless daemon — uses §8.2 code):**
```
IEP3 is a portless asyncio daemon in retail-edge/. Add prometheus-client to its
requirements.txt and instrument it per §8.2 of docs/PROMETHEUS_GRAFANA_GUIDE.md:
define module-level Counter/Histogram/Gauge metrics (iep3_batches_processed_total,
iep3_batch_reconcile_seconds, iep3_reid_matches_total, iep3_reid_new_identities_total,
iep3_global_identities{state}), call start_http_server(9300) once at startup before
the coordinator loop, and update the metrics inside the real reconcile path (find it,
don't invent it). Also add `expose: ["9300"]` to the iep3 service in docker-compose.
Show me where you hooked the metric updates so I can confirm they're on the hot path.
```
✅ **Expect / verify (IEP3, after rebuild + restart):**
1. **Endpoint exists:** `docker compose exec iep3_reconciliation curl -s localhost:9300/metrics | head`
   → plain-text `# HELP ...` / `# TYPE ...`. If curl connection-refuses, the metrics
   server didn't start — check `docker compose logs iep3_reconciliation` (common cause:
   `start_http_server(9300)` never reached, or the port is already bound).
2. **Prometheus sees it:** http://localhost:9090/targets → `iep3` flips from **DOWN to
   UP** (may take up to one 15s scrape interval — wait and refresh).
3. **Data is real:** http://localhost:9090/graph → query `iep3_batches_processed_total`
   → run some pipeline traffic → the number should **climb**. A metric stuck at 0 means
   you wired the endpoint but the `.inc()` isn't on the executed code path — tell Claude
   *"iep3_batches_processed_total stays 0 even though batches are processing; show me the
   reconcile call path and confirm the counter increment runs there."*

### Step 6 — (optional, Tier 2) Instrument the detector for a latency panel
Add a metrics thread alongside the detector's existing gRPC health server (§8.4) for
inference latency / batch-size. **(The ReID service is deferred to Phase 2 — the
detector alone is enough for the Tier 2 latency story.)**

> **Naming:** the detector model is RT-DETR-x (`rtdetr-x.pt`) in prod, YOLO11n in dev.
> Name the metrics `detector_*` (not `yolo_*`) so they're accurate either way. The
> compose **service name stays `yolo-service`**; the Prometheus **job is `detector`**.

📋 **Claude Code prompt (detector only):**
```
The detector service in retail-edge/ (services/yolo_service/service_dev.py — the dev
file that actually runs) already runs a gRPC health server in a thread. Add
prometheus-client to its requirements and, next to where the health server starts,
call start_http_server(9400). Define histograms for inference latency
(detector_inference_seconds) and batch size (detector_batch_size), a
detector_frames_total + detector_detections_total counter, and a
detector_info{model=...} gauge set from DETECTOR_MODEL, recorded in the real inference
loop (locate it, don't invent it). Add expose: ["9400"] to the yolo-service in
docker-compose, and add a Prometheus job named "detector" pointing at yolo-service:9400.
Show me the inference-loop edits so I can confirm they're on the hot path.
```
✅ **Expect / verify:** the detector image has no `curl`, so scrape from the prometheus
container: `docker compose exec prometheus wget -qO- http://yolo-service:9400/metrics | grep detector_`
shows metrics; http://localhost:9090/targets shows `detector` **UP**;
`detector_info` carries the right `model` label; and on http://localhost:9090/graph,
`rate(detector_frames_total[1m])` is **> 0 while video is flowing**. Zero rate with
traffic running = the `.observe()/.inc()` calls aren't in the executed loop.

### Step 7 — Build the Phase 1 dashboards, then export to files
Build panels with PromQL (§9), then export each dashboard JSON so it's reproducible.
Phase 1 ships **three** dashboards: *Stream Health* (Tier 1), *Reconciliation &
Identities* and *Inference Latency* (Tier 2).

📋 **Claude Code prompt (let Claude scaffold the JSON so you barely touch the UI):**
```
Generate Grafana dashboard JSON files (schema compatible with current Grafana,
datasource "Prometheus") into
retail-edge/monitoring/grafana/provisioning/dashboards/ :

1. stream-health.json — "Stream Health":
   - Time series: redis_stream_length by stream (legend {{stream}})
   - Stat: redis_connected_clients
   - Time series: rate(http_requests_total[5m]) for eep, split by status

2. reconciliation.json — "Reconciliation & Identities":
   - Time series: iep3_global_identities by state (legend {{state}})
   - Time series: cross-camera link rate (the iep3 matches / (matches+new) ratio
     from §9)
   - Time series: p95 of iep3_batch_reconcile_seconds via histogram_quantile

3. inference-latency.json — "Inference Latency":
   - Time series: p95 of detector_inference_seconds via histogram_quantile
   - Histogram/heatmap: detector_batch_size distribution
   (If detector step 6 was skipped, create this file with the panels but expect "No
   data" until the detector is instrumented.)
```
Alternatively build them by hand in the UI (http://localhost:3001 →
**Dashboards → New → Add visualization**, pick the Prometheus datasource, paste a
PromQL query from §9), then **Dashboard settings → JSON Model → copy** into the same
`dashboards/` folder.

✅ **Expect / verify:** Restart Grafana so provisioning re-reads the files:
`docker compose restart grafana`. Then http://localhost:3001 → **Dashboards →
RetailVision** folder → your dashboards appear **automatically** and render live data
(not "No data"). If a panel says **No data**: copy its PromQL into
http://localhost:9090/graph — if Prometheus has no data either, the metric/instrument-
ation is the problem (back to Step 5/6); if Prometheus *does* show data, the panel's
query or datasource is wrong (ask Claude to fix the panel JSON).

> ✅ **Tier 2 milestone reached.** All three dashboards live = the recommended
> deliverable is done.

### Step 8 — Document for the grader
📋 **Claude Code prompt:**
```
Add a "Monitoring (Prometheus + Grafana)" section to retail-edge/README.md using the
grader-facing instructions in §10 of docs/PROMETHEUS_GRAFANA_GUIDE.md: how to start
the stack with monitoring, the Grafana URL + login (password from .env
GRAFANA_PASSWORD), where to find the RetailVision dashboards, and that they're
provisioned from files so they appear automatically. Keep it short.
```
✅ **Expect / verify:** README has the section; do a clean dry-run yourself — from a
fresh `docker compose ... up -d`, follow *only* what the README says and confirm you
land on a live dashboard. If you can, so can the grader.

### Step 9 — Add infrastructure exporters (postgres + node)
Ready-made exporters → host/DB health with zero app code (§5.7). Cheap, high-signal,
and they make the targets page tell a fuller "is the platform healthy?" story.

📋 **Claude Code prompt:**
```
In retail-edge/, add two ready-made exporters to docker-compose:
1. postgres_exporter (quay.io/prometheuscommunity/postgres-exporter) with
   DATA_SOURCE_NAME pointing at the project's Postgres (reuse the existing
   POSTGRES_* env / connection — find it, don't hardcode credentials), port 9187.
2. node_exporter (prom/node-exporter) on port 9100 for host CPU/RAM.
Then add matching scrape jobs (postgres -> postgres_exporter:9187, node ->
node_exporter:9100) to monitoring/prometheus.yml. Show me the compose + prometheus.yml
diffs.
```
✅ **Expect / verify:** `docker compose up -d postgres_exporter node_exporter`, then
http://localhost:9090/targets shows `postgres` and `node` **UP**. On
http://localhost:9090/graph, `pg_up` returns `1` and `node_memory_MemAvailable_bytes`
returns a value. (Optional follow-up prompt: *"add an Infrastructure Health dashboard
JSON with pg connections, node CPU and node memory panels into
monitoring/grafana/provisioning/dashboards/, then restart grafana."*)

### Step 10 — Alerting rules (the "it tells you when it breaks" part)
Add Prometheus alert rules for the failure modes that matter to RetailVision. This is
the single most impressive Phase 1 addition — a firing-then-clearing alert proves the
monitoring is *actually* watching the pipeline, not just drawing graphs.

📋 **Claude Code prompt:**
```
Create monitoring/alert_rules.yml with Prometheus alerting rules for RetailVision:
1. NoFramesFlowing: rate(detector_frames_total[2m]) == 0 for 2m (pipeline stalled).
   (If detector step 6 was skipped, base this on rate(http_requests_total[2m]) for eep
   instead, or on iep3_batches_processed_total — pick a counter that's actually
   instrumented.)
2. RedisStreamBacklog: redis_stream_length{stream=~"stream:iep.*"} > <pick a sane
   threshold> for 5m (a stage falling behind).
3. IEP3ReconcileSlow: histogram_quantile(0.95, ...iep3_batch_reconcile_seconds...) >
   <threshold> for 5m.
4. TargetDown: up == 0 for 1m.
Give each a severity label and a summary/description annotation. Then wire it into
monitoring/prometheus.yml via a top-level `rule_files: [ "alert_rules.yml" ]` and mount
the file into the prometheus container. Show me both diffs.
```
✅ **Expect / verify:**
- After `docker compose restart prometheus`, open
  **http://localhost:9090/rules** → all four rules appear and are **green/OK** under
  normal operation.
- **Force one to fire to prove it works:** stop the video feed (or scale YOLO to 0) so
  no frames flow; within ~2 min **http://localhost:9090/alerts** shows
  `NoFramesFlowing` go **PENDING → FIRING**. Restart the feed → it clears. *Demonstrate
  this in your write-up — a firing-then-clearing alert is the strongest evidence the
  monitoring is real.*
- (Optional) wire Alertmanager for notifications — ask Claude, but for a demo the
  firing state on the Alerts page is usually enough.

### ✅ Phase 1 done — checkpoint before deciding on Phase 2
Before you even consider Phase 2, confirm all of these are true (this is also your
"Phase 1 acceptance test"):

📋 **Claude Code prompt (final Phase 1 audit):**
```
Audit my Phase 1 monitoring setup in retail-edge/. Check and report PASS/FAIL for:
1. monitoring/prometheus.yml exists and lists eep, iep3, redis, postgres, node jobs.
2. redis_exporter + postgres_exporter + node_exporter + the prometheus config mount
   are in docker-compose and `docker compose config` succeeds.
3. Grafana datasource + dashboard providers are provisioned, and these files exist:
   dashboards/stream-health.json, reconciliation.json, inference-latency.json.
4. monitoring/alert_rules.yml exists, is referenced via rule_files in prometheus.yml,
   and shows on http://localhost:9090/rules.
5. README has the Monitoring section.
Then curl http://localhost:9090/api/v1/targets and tell me which of prometheus,
redis, eep, iep3, postgres, node (and yolo if done) are UP. List anything still missing.
```
✅ **Expect / verify:** every item **PASS**; `prometheus`, `redis`, `eep`, `iep3`,
`postgres`, `node` (and `yolo` if you did Step 6) all **UP**; three dashboards present
and rendering live data; alert rules visible on `/rules` and you've seen at least one
fire and clear. **If all green, Phase 1 is complete — this is a legitimate stopping
point.** Only proceed to Phase 2 if you actively want the production-grade extras.

---

# PHASE 2 — Tier 3 (only if you continue after Phase 1) 🚀

> **Start condition:** Phase 1 is finished and the Step-10 checkpoint is all-green.
> Phase 2 *adds to* the same `monitoring/` directory and the already-running stack —
> you are not rebuilding anything. Each step is independent, so you can do any subset
> and skip the rest. **Estimated effort: +1 day.**
>
> Tier 3 here = the remaining service instrumentation (Live Bridge + the ReID service)
> and the edge push model (Pushgateway / remote_write). (Infra exporters and alerting
> were pulled forward into Phase 1.) See §11 "Tier 3" and §4 for the rationale; this
> section is the executable version.

### Step 11 — Instrument Live Bridge + the ReID service (the deferred services)
Finish the two services Phase 1 skipped. Same patterns as before (§8.1 FastAPI for
Live Bridge, §8.4 metrics-thread for the ReID service). The ReID service is the
`reid-service` container (resnet50_msmt17) — *not* "osnet".

📋 **Claude Code prompt (Live Bridge — FastAPI):**
```
Live Bridge is a FastAPI app in retail-edge/. Add prometheus-fastapi-instrumentator
and prometheus-client to its requirements.txt, and after `app = FastAPI(...)` add
Instrumentator().instrument(app).expose(app). Then add the custom metrics from §5.2:
live_bridge_active_connections{camera} (gauge), live_bridge_frames_relayed_total{camera}
(counter), live_bridge_presign_seconds (histogram) — wired into the real WebSocket /
presign code paths (locate them). Show me the edits, then rebuild and restart live_bridge.
```
📋 **Claude Code prompt (ReID service — metrics thread):**
```
The reid-service in retail-edge/ (services/reid_service/service_dev.py is the dev file
that runs; resnet50_msmt17) runs a gRPC health server in a thread. Add prometheus-client,
call start_http_server(9401) next to the health server, and define reid_embedding_seconds
(histogram), reid_batch_size (histogram), reid_embeddings_total (counter), recorded in
the real embedding loop. Add expose: ["9401"] to the reid-service in docker-compose, and
a Prometheus job "reid" -> reid-service:9401. Show me the embedding-loop edits.
```
✅ **Expect / verify:**
- `docker compose exec live_bridge curl -s localhost:8010/metrics | head` shows metrics,
  and (reid image may lack curl) `docker compose exec prometheus wget -qO-
  http://reid-service:9401/metrics | grep reid_` shows metrics.
- http://localhost:9090/targets → `live_bridge` and `reid` now **UP** (these were the
  last two DOWN app targets from Step 4 — the targets page should now be **all green**
  except any intentionally skipped edge jobs).
- http://localhost:9090/graph → `rate(reid_embeddings_total[1m])` > 0 under traffic.

### Step 12 — The edge push model (Pushgateway / remote_write) for IEP1/IEP2
The hard part from §4: edge daemons can't be scraped directly. **This is the most
complex and least-demo-value step — do it last, or just document it.**

📋 **Claude Code prompt (Pushgateway path — simpler):**
```
Implement the cloud Pushgateway path described in §4 of
docs/PROMETHEUS_GRAFANA_GUIDE.md:
1. Add a `pushgateway` service (prom/pushgateway) on port 9091 to retail-edge
   docker-compose, and a scrape job for it in monitoring/prometheus.yml with
   honor_labels: true.
2. In the IEP1 and IEP2 edge daemons, add prometheus-client and push a small set of
   metrics (e.g. iep1_frames_total, iep2_batches_total + per-camera labels) to the
   Pushgateway using push_to_gateway / a periodic pusher, keyed by a stable
   grouping job + camera label. Find the daemon main loops; don't invent them.
Explain the network assumption (edge must be able to reach the cloud Pushgateway URL)
and where I set that URL via env.
```
✅ **Expect / verify:**
- `docker compose up -d pushgateway`; open **http://localhost:9091** → after the edge
  daemons run, you see their pushed metrics listed there.
- http://localhost:9090/targets → `pushgateway` is **UP**; on /graph,
  `iep1_frames_total` (with camera labels) returns data that **originated on the edge**.
- **Reality check:** if the edge can't reach the cloud Pushgateway URL (NAT/firewall),
  the push silently fails — confirm by checking the daemon logs for push errors. If you
  can't make the network path work in your environment, that's fine: **document this as
  the known limitation and the `remote_write` alternative**, which is itself a valid
  Tier 3 write-up. Ask Claude: *"write a short 'scaling monitoring to the edge' note
  for the README covering Pushgateway vs edge-Prometheus remote_write and the NAT
  constraint."*

### ✅ Phase 2 done
📋 **Claude Code prompt (final Tier 3 audit):**
```
Audit my Phase 2 / Tier 3 additions in retail-edge/. Report PASS/FAIL for: live_bridge
and reid exposing /metrics and UP in Prometheus; pushgateway service present and UP
(or the edge limitation documented in README). curl
http://localhost:9090/api/v1/targets and list every target's UP/DOWN state.
```
✅ **Expect / verify:** the targets page is **all green** (minus any edge job you chose
to leave as documented-only), now including `live_bridge` and `reid` on top of the
Phase 1 targets. That's the complete production-ish monitoring story.

---

## 8. The instrumentation code (copy-paste)

Add `prometheus-client` (and for FastAPI, `prometheus-fastapi-instrumentator`) to
each service's `requirements.txt`.

### 8.1 EEP / Live Bridge (FastAPI) — the easy win
```python
# in app/main.py, after `app = FastAPI(...)`
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)   # adds GET /metrics
```
That single block gives request count, latency histogram, and error rate at
`/metrics`. For a custom metric:
```python
from prometheus_client import Counter
GRPC_COMMANDS = Counter("eep_grpc_commands_total", "Start/Stop sent to edge", ["type"])
# when you send a command:
GRPC_COMMANDS.labels(type="start").inc()
```

### 8.2 IEP3 (portless daemon) — add a metrics server thread
```python
# near the top of app/main.py
from prometheus_client import start_http_server, Counter, Histogram, Gauge

IEP3_BATCHES   = Counter("iep3_batches_processed_total", "Batches reconciled")
IEP3_RECONCILE = Histogram("iep3_batch_reconcile_seconds", "Reconcile time per batch")
IEP3_MATCHES   = Counter("iep3_reid_matches_total", "Cross-camera ReID matches")
IEP3_NEW       = Counter("iep3_reid_new_identities_total", "New global identities")
IEP3_GLOBALS   = Gauge("iep3_global_identities", "Global identities by state", ["state"])

# in startup, before the coordinator loop:
start_http_server(9300)     # exposes /metrics on :9300

# inside the reconcile path:
with IEP3_RECONCILE.time():
    result = reconciler.reconcile(batch)
IEP3_BATCHES.inc()
IEP3_MATCHES.inc(result.matches)
IEP3_NEW.inc(result.new_identities)
IEP3_GLOBALS.labels(state="active").set(result.active_count)
```
> `start_http_server` runs its own background thread — it does **not** interfere with
> IEP3's asyncio loop. Just don't reuse a port already bound.

### 8.3 Expose the port in Compose
For IEP3 (and the detector/ReID services), publish the metrics port so Prometheus can
reach it (within the Compose network it's reachable by service name even without
`ports:`, but exposing helps debugging):
```yaml
  iep3_reconciliation:
    # ...existing...
    expose: ["9300"]      # visible to Prometheus on the Compose network
```

### 8.4 Detector / ReID — metrics thread beside the health server
```python
# alongside the existing health-server startup in service_dev.py
from prometheus_client import start_http_server, Histogram, Counter, Gauge
DETECTOR_INFER = Histogram("detector_inference_seconds", "Detection latency per batch")
DETECTOR_BATCH = Histogram("detector_batch_size", "Batch size", buckets=[1,2,4,8,16,32])
DETECTOR_FRAMES = Counter("detector_frames_total", "Frames processed")
DETECTOR_INFO = Gauge("detector_info", "Loaded model (value 1)", ["model"])

start_http_server(9400)
DETECTOR_INFO.labels(model=os.path.basename(DETECTOR_MODEL)).set(1)

# in _infer_batch / the inference loop:
DETECTOR_BATCH.observe(len(batch_items))
with DETECTOR_INFER.time():
    results = model(frames, ...)
DETECTOR_FRAMES.inc(len(frames))
```
> The ReID service follows the same pattern on `:9401` with `reid_*` names
> (`reid_embedding_seconds`, `reid_batch_size`, `reid_embeddings_total`).

---

## 9. PromQL — the query language you need

PromQL is how Grafana panels ask Prometheus for data. You need ~6 patterns:

| Goal | PromQL |
|---|---|
| Current value of a gauge | `iep3_global_identities{state="active"}` |
| **Rate** of a counter (per-second, over 5 min) | `rate(detector_frames_total[5m])` |
| Frames/sec **per camera** | `sum by (camera) (rate(detector_frames_total[5m]))` |
| 95th-percentile latency from a histogram | `histogram_quantile(0.95, sum by (le) (rate(detector_inference_seconds_bucket[5m])))` |
| Error rate (% of requests) | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` |
| Cross-camera link rate (your key IEP3 ratio) | `rate(iep3_reid_matches_total[5m]) / (rate(iep3_reid_matches_total[5m]) + rate(iep3_reid_new_identities_total[5m]))` |
| Redis stream depth | `redis_stream_length{stream="stream:iep2:batch_complete"}` |

**Two rules that trip up beginners:**
1. **Always `rate()` a counter** before graphing it — a raw counter is a meaningless
   ever-rising line. `rate(x_total[5m])` gives per-second change.
2. For histogram percentiles, query the **`_bucket`** series with
   `histogram_quantile(...)`, not the raw metric.

---

## 10. Building dashboards & how the grader views them

### Build (once, in the UI)
1. http://localhost:3001 → **Dashboards → New → Add visualization**.
2. Pick the **Prometheus** datasource, paste a PromQL query (§9), choose a viz
   (Time series / Gauge / Stat / Table).
3. Repeat for each panel; arrange them; **Save**.
4. **Dashboard settings → JSON Model → copy** → save to
   `monitoring/grafana/provisioning/dashboards/<name>.json`. Now it's reproducible.

### Suggested starter dashboards (4 panels each is plenty)
- **Pipeline Throughput** — frames/sec per camera (YOLO), batches/sec (IEP3),
  detections/sec.
- **Inference Latency** — p95 detector + ReID latency, batch-size distribution.
- **Reconciliation & Identities** — active/lost/exited gauges, cross-camera link
  rate, reconcile-time p95.
- **Stream Health** — `redis_stream_length` for IEP1 and IEP2 streams, consumer
  lag. (The most project-specific one.)

### How the grader views it (put this in your README)
> **Viewing the live dashboards (Grafana)**
> 1. From `retail-edge/`, start the stack incl. monitoring:
>    `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
> 2. Open **http://localhost:3001** (user `admin`, password from `.env`
>    `GRAFANA_PASSWORD`).
> 3. Left sidebar → **Dashboards → RetailVision** → open any dashboard.
> 4. Graphs update live while the pipeline runs. Use the time-range picker (top
>    right) to zoom.
> 5. Raw metrics/queries are also at **http://localhost:9090** (Prometheus).

Dashboards are provisioned from files, so they appear automatically.

---

## 11. Are you overdoing it? Scope by time budget

**Like MLflow, the full thing (every service, edge push model, alerting) is more
than a uni demo needs.** Tiers:

### Tier 1 — "Demonstrate the chain" (½ day) ✅ minimum viable
- `prometheus.yml` + **EEP `/metrics`** + **`redis_exporter`** + Grafana datasource
  + **one** dashboard (Stream Health + EEP request rate).
- Proves the entire pull→store→visualize chain end to end. A grader sees live data.

### Tier 2 — "Solid, project-specific" (1 day) ⭐ recommended
- Tier 1 **plus IEP3 metrics** (the brain) **plus a YOLO latency panel**.
- Dashboards: *Stream Health*, *Reconciliation & Identities*, *Inference Latency*.
- This tells the real RetailVision story: throughput, identity quality, and the
  silent-stall failure mode — all cloud-side, no edge complexity.

### Tier 3 — "Complete / production-ish" (2–3 days)
- Add Live Bridge + ReID metrics, `postgres_exporter` + `node_exporter`/cAdvisor,
  **alerting rules** ("no frames 2 min", "IEP3 lag high"), and the **edge push
  model** (Pushgateway or remote_write) for IEP1/IEP2.

> **Note on phasing (§7):** the §7 build plan deliberately pulls the two *cheapest,
> highest-signal* Tier 3 items — `postgres`/`node` exporters and **alerting rules** —
> **forward into Phase 1**, because they're low effort and a firing alert is strong
> demo evidence. Phase 2 then carries only the heavier Tier 3 work: Live Bridge +
> ReID-service instrumentation and the edge push model.

### What to cut first when short on time
1. **Edge instrumentation (IEP1/IEP2)** — the Pushgateway/NAT work. Biggest effort,
   least demo payoff. Cut first.
2. **Alerting rules** — nice but not needed to *show* monitoring.
3. **Extra exporters** (postgres/node) — keep `redis_exporter`, drop the rest.
4. Keep **EEP `/metrics` + redis_exporter + one dashboard** no matter what.

### True overkill for this project
- The full kube-prometheus-stack / prometheus-operator on k8s.
- Long-term storage (Thanos/Cortex), high-availability Prometheus.
- Per-frame or per-request metric explosions (high-cardinality labels — see §14).
- Recreating in Grafana what MLflow already shows (model accuracy is *not* a
  Grafana concern).

---

## 12. The minimal "enough" metric set

If you do only the minimum, expose **exactly these** — chosen to tell the pipeline
story with the fewest moving parts:

| Source | Metric | Why it's enough |
|---|---|---|
| `redis_exporter` (free) | `redis_stream_length{stream}` | Shows IEP1→IEP2→IEP3 flow and stalls — the killer panel, zero code |
| EEP (free instrumentator) | `http_request_duration_seconds`, `http_requests_total` | API health + error rate, 2 lines of code |
| IEP3 | `iep3_batches_processed_total`, `iep3_batch_reconcile_seconds`, `iep3_global_identities{state}` | The brain working + identity counts |
| Detector (optional) | `detector_inference_seconds`, `detector_frames_total` | Detection latency + throughput |

**That's ~4 sources, ~8 metrics, 2 dashboards.** More than enough to demonstrate
Prometheus + Grafana competently. Adding more metrics makes dashboards noisier, not
better — pick one primary signal per service.

**The single most valuable thing per effort:** `redis_exporter` →
`redis_stream_length` dashboard. **Zero code, maximally project-relevant.** Do this
even in Tier 1.

---

## 13. Everything you should know to actually use them

### 13.1 The `/metrics` format (what a scrape actually reads)
A `/metrics` page is just plain text Prometheus parses:
```
# HELP detector_frames_total Frames processed
# TYPE detector_frames_total counter
detector_frames_total{camera="cam1"} 1234
detector_inference_seconds_bucket{le="0.05"} 87
detector_inference_seconds_bucket{le="0.1"} 142
detector_inference_seconds_sum 18.4
detector_inference_seconds_count 200
```
You never write this by hand — the `prometheus_client` library generates it from
your Counter/Gauge/Histogram objects.

### 13.2 Defining and updating metrics (the whole client API)
```python
from prometheus_client import Counter, Gauge, Histogram, start_http_server

C = Counter("things_total", "desc", ["label"])      # define ONCE at module level
G = Gauge("current_things", "desc")
H = Histogram("op_seconds", "desc", buckets=[.01,.05,.1,.5,1,5])

C.labels(label="a").inc()       # +1
C.labels(label="a").inc(5)      # +5
G.set(42)                       # set absolute value
G.inc(); G.dec()                # adjust
H.observe(0.123)                # record a value
with H.time():                  # time a block → auto .observe()
    do_work()

start_http_server(9300)         # serve /metrics on :9300 (own thread)
```
**Define metric objects once at import time** (module level), not inside functions —
re-defining the same name errors.

### 13.3 Labels — powerful but dangerous
Labels split one metric into many series (`{camera="cam1"}`, `{camera="cam2"}`).
- ✅ Good labels: low-cardinality, bounded sets — `camera`, `stage`, `state`,
  `status`.
- ❌ **Never** put unbounded values in labels — `user_id`, `request_id`,
  `timestamp`, `local_id`. Each unique value = a new stored series; this is
  "cardinality explosion" and will OOM Prometheus. (See §14.)

### 13.4 Checking targets & debugging
- **http://localhost:9090/targets** — every target shows **UP/DOWN** + last scrape
  + error. First stop when a metric is missing.
- **http://localhost:9090/graph** — type a metric name, hit Execute, see raw values.
  Confirm the metric exists here before debugging Grafana.
- **curl the endpoint directly:** `docker compose exec eep curl -s localhost:8000/metrics | head`
  — proves the service exposes data independent of Prometheus.

### 13.5 Reading data in Grafana
- A **panel** = one or more PromQL queries + a visualization.
- **Time range** (top-right) controls the window; **refresh** sets auto-update.
- **Legend** uses label values — `{{camera}}` in the legend format names each line.
- **Variables** (dashboard settings) let you add a dropdown, e.g. pick a camera —
  define `$camera` from `label_values(detector_frames_total, camera)`.

### 13.6 Where data lives & retention
- Prometheus stores in its **own TSDB volume** (`prometheus_data`), default ~15
  days. Change with `--storage.tsdb.retention.time=30d` in the container command.
- Grafana stores dashboards/users in `grafana_data` (SQLite). Provisioned
  dashboards live in files (read-only in the UI).
- **Neither uses your Postgres/MinIO** — different from MLflow.

### 13.7 Naming conventions (adopt these)
- Counters end in `_total`. Use base units: `_seconds`, `_bytes` (not `_ms`).
- Prefix by service: `iep3_`, `detector_`, `eep_`.
- Metric names = what is measured; **dimensions go in labels**, not in the name.
  (`detector_frames_total{camera="cam1"}`, *not* `detector_frames_cam1_total`.)

### 13.8 Minimal end-to-end check (do before real instrumentation)
1. Add the FastAPI instrumentator to EEP, rebuild, start.
2. `docker compose exec eep curl -s localhost:8000/metrics | head` → see metrics.
3. http://localhost:9090/targets → `eep` is **UP**.
4. http://localhost:9090/graph → query `http_requests_total` → see a value.
5. Grafana → new panel → same query → see a line.
If all five pass, your whole chain works; everything else is more metrics + panels.

---

## 14. Common mistakes & how to avoid them

| Mistake | Symptom | Fix |
|---|---|---|
| No `prometheus.yml` mounted | Prometheus runs but scrapes nothing | Mount `monitoring/prometheus.yml` (Step 2) — *this is why the container currently does nothing* |
| Using `localhost` in targets | Targets DOWN inside Compose | Use the **service name** (`eep:8000`) |
| Graphing a raw counter | Meaningless ever-rising line | Wrap in `rate(x_total[5m])` |
| High-cardinality labels (`request_id`, `local_id`) | Prometheus memory blows up | Only bounded labels (camera, state, status) |
| Defining a metric inside a function | `Duplicated timeseries` / errors | Define metric objects once at module level |
| Trying to scrape edge IEP2 pods from cloud | Targets unreachable / flapping | Skip edge for demo, or use Pushgateway (§4) |
| Dashboards built only in UI | Lost on container reset; grader sees nothing | Export JSON to `provisioning/dashboards/` |
| Expecting metrics in Postgres | "where's my data?" | Prometheus has its **own** TSDB, not Postgres |
| Port already in use for `start_http_server` | Daemon crashes on startup | Give each service a unique metrics port (9300/9400/9401) |

---

## 15. Glossary & FAQ

**Pull model** — Prometheus fetches metrics from your services on a timer (vs you
pushing). The core paradigm. Push exists (Pushgateway) only for special cases like
edge/batch jobs.

**Exporter** — a small program that exposes someone else's system as Prometheus
metrics (e.g. `redis_exporter` exposes Redis). Saves you writing code.

**TSDB** — time-series database; Prometheus's storage engine.

**Scrape interval** — how often Prometheus pulls (15s here). Smaller = more
resolution + more storage.

**Cardinality** — the number of distinct label-value combinations = number of stored
series. Keep it low.

**Q: Is this the same as MLflow?** No. MLflow = offline model selection, *you* log
once per run, stored in Postgres+MinIO. Prometheus/Grafana = online runtime health,
*services expose* metrics, Prometheus pulls them into its own TSDB, Grafana shows
them live. Opposite halves of the ML lifecycle. (See [`MLFLOW_GUIDE.md`](MLFLOW_GUIDE.md).)

**Q: Separate containers?** Yes — Prometheus and Grafana are two separate
containers (already in your compose), plus exporters as extra containers. Your app
services just grow a `/metrics` endpoint (no new container).

**Q: Do I need Kubernetes?** No — Compose is enough. k8s only matters if you later
auto-scrape edge pods (kube-prometheus-stack) — out of scope.

**Q: Does it need a GPU?** No. Prometheus/Grafana are CPU-only. They *measure* GPU
usage if you add a GPU exporter, but don't need one.

**Q: Will instrumentation slow my services?** Negligibly — incrementing a counter is
nanoseconds. Just avoid high-cardinality labels.

**Q: Can Grafana read my app's Postgres directly for business charts?** Yes, Grafana
supports a Postgres datasource — but that's a *separate* use (querying business
data), not pipeline monitoring. Keep the monitoring dashboards on Prometheus.

---

## 16. Final recommendation

**For a uni project short on time, do Tier 2 (§11) and stop:**

1. `monitoring/prometheus.yml` + mount it (this alone "activates" the empty
   container).
2. **`redis_exporter`** → **Stream Health** dashboard (zero code, most
   project-relevant). Non-negotiable — do this first.
3. **EEP `/metrics`** (2-line FastAPI instrumentator) → request rate + latency.
4. **IEP3 metrics** (batches, reconcile time, identity gauges) → *Reconciliation &
   Identities* dashboard — your brain, the impressive part.
5. Provision the Grafana datasource + export your dashboards to files so the grader
   sees them automatically.
6. **Skip the edge (IEP1/IEP2) instrumentation, alerting, and extra exporters** —
   note the Pushgateway/remote_write path as "future work."

Use the §12 minimal metric set (~8 metrics, 2 dashboards), label only with bounded
values, always `rate()` counters, and export dashboards to
`monitoring/grafana/provisioning/`. That is a complete, honest monitoring story for
RetailVision without overdoing it.

**If you are *really* short on time:** `prometheus.yml` + `redis_exporter` + EEP
`/metrics` + one Grafana dashboard. ~2 hours, and it demonstrates the entire
Prometheus→Grafana skillset end to end.
```