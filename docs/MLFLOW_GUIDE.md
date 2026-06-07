# MLflow for RetailVision — Implementation Guide (Tier 2 plan)

> **Audience:** someone who has *never used MLflow*. This guide explains what MLflow
> is, exactly how it fits this project, what to log for **detection, tracking, and
> ReID**, the **exact runs** to execute, how to use **Claude Code** to do the work
> fast, where results are stored, and how a grader inspects them.
>
> **Scope decision (locked in):** This guide covers **three experiments —
> `detection`, `tracking`, `reid`. Reconciliation (IEP3) is intentionally OUT of
> scope** for MLflow. This is the Tier-2 plan (see §12): complete, honest, and
> defensible without overdoing it.

## Your plan in one box

```
Tier 2 — do this and stop:
  • detection — comparison (4 models) + conf tuning sweep
  • tracking  — comparison (4 trackers) + 3-point match_thresh sweep (tagged no_effect)
  • reid      — comparison (candidate models) + reid_threshold sweep
  • Reconciliation: SKIPPED (not doing MLflow for it)

Discipline applied to every run:
  • run = (model × video)         ← Gap 6: log `scene` so you can filter mannequin vs crowded
  • process each clip to completion (all frames), never stop on a timer   ← Gap 1
  • tag every run: phase ∈ {comparison,tuning}, scene ∈ {mannequin,crowded}, metric_type
  • log reproducibility context: seed, exact weights filename, git_commit, requirements.txt ← Gap 5
  • 4–6 metrics per experiment (§13), programmable (no ground truth) + later labeled metrics

Your three real videos (ground truth already known) — TWO metric regimes:
  • clip_mannequin.mp4         — 33 s, 0 real people, 8 MANNEQUINS        → scene=mannequin
  • hand_on_ad_in_store.mp4    — 0 real people, 1 printed HAND on an ad   → scene=hand_ad
        ^ both above are 0-people clips → every detection is a false positive
          → measure false_positive_total (+ false_positive_per_frame)
  • clip_cashier.mp4           — 16 distinct people (peak 14) at two cashier stations → scene=crowded
        ^ people-counting clip → measure count_error (vs 16), peak_count_error (vs 14)

Why two FP clips: RT-DETR rejects 3-D mannequins structurally but still mis-detects
a 2-D printed human (detection_experiments Case 3). hand_ad tests that exact gap.

Ground truth (phased):
  Phase 1 (DONE — values known): mannequin total_people=0 fp_object_count=8;
           hand_ad total_people=0 fp_object_count=1; cashier total_people=16 peak=14
  Phase 2 (optional, later): per-frame people count on a few sampled frames of clip_cashier
```

---

## Table of Contents

1. [What MLflow is (plain English)](#1-what-mlflow-is-plain-english)
2. [The four MLflow concepts you must know](#2-the-four-mlflow-concepts-you-must-know)
3. [How MLflow fits RetailVision — the plan](#3-how-mlflow-fits-retailvision--the-plan)
4. [Repo structure: the `mlops/` folder](#4-repo-structure-the-mlops-folder)
5. [What to log per module (the metric lists)](#5-what-to-log-per-module-the-metric-lists)
6. [Answering your direct questions](#6-answering-your-direct-questions)
7. [Step-by-step implementation (with Claude Code prompts)](#7-step-by-step-implementation-with-claude-code-prompts)
8. [The logging helper + example scripts](#8-the-logging-helper--example-scripts)
9. [How the grader opens the results](#9-how-the-grader-opens-the-results)
10. [The exact runs to execute (detection / tracking / reid)](#10-the-exact-runs-to-execute-detection--tracking--reid)
11. [Ground-truth labeling (phased) + the metrics it unlocks](#11-ground-truth-labeling-phased--the-metrics-it-unlocks)
12. [Scope: why Tier 2 is the right amount](#12-scope-why-tier-2-is-the-right-amount)
13. [The minimal "enough" metric sets](#13-the-minimal-enough-metric-sets)
14. [Everything you should know to actually use MLflow](#14-everything-you-should-know-to-actually-use-mlflow)
15. [Common mistakes & how to avoid them](#15-common-mistakes--how-to-avoid-them)
16. [Final recommendation & end-to-end checklist](#16-final-recommendation--end-to-end-checklist)

---

## 1. What MLflow is (plain English)

MLflow is a **lab notebook for machine-learning experiments**. Today, your model
comparisons live as **hand-written markdown tables** in `docs/docs_models/`
(detection, tracking, reid). Every time you ran a model you wrote the numbers into
a table by hand.

MLflow replaces that manual table with a **database + web UI** that records, for
every experiment run:

- **what you ran** (model name, thresholds, video) — *parameters*
- **what came out** (unique people, ID switches, confidence…) — *metrics*
- **files produced** (annotated clips, plots, the model weights) — *artifacts*

…and then lets you **sort, filter, and compare runs side by side in a browser**.
Instead of "trust my markdown table," the grader opens a UI, clicks two runs, and
sees the comparison generated from real logged data.

**Crucial mental model:** MLflow is **offline**. It is *not* monitoring your live
pipeline (that is Prometheus/Grafana's job). MLflow is for **"which model/config is
best?"** — you run an evaluation script, it logs to MLflow, you compare. It has
nothing to do with IEP1/IEP2/IEP3 running in production.

---

## 2. The four MLflow concepts you must know

| Concept | What it is | RetailVision example |
|---|---|---|
| **Experiment** | A named folder grouping related runs | `detection`, `tracking`, `reid` |
| **Run** | One execution of your eval (one model on **one video**, with its config) | "rtdetr-x @ conf=0.3 on clip_cashier" |
| **Param** | An input you chose (fixed for the run) | `model=rtdetr-x`, `conf=0.3`, `scene=crowded` |
| **Metric** | A number that came out (the result) | `unique_people=17`, `id_switches=12` |
| **Artifact** | A file the run produced | annotated video, score histogram, `requirements.txt` |

In code it is literally:

```python
import mlflow
mlflow.set_experiment("detection")          # pick the folder
with mlflow.start_run(run_name="rtdetr-x_conf0.3_cashier"):  # start ONE run
    mlflow.log_param("model", "rtdetr-x")   # inputs
    mlflow.log_param("conf", 0.3)
    mlflow.set_tag("scene", "crowded")
    mlflow.log_metric("unique_people", 17)  # outputs
    mlflow.log_artifact("outputs/cashier_annotated.mp4")  # files
```

That's the entire API surface you need for this project.

---

## 3. How MLflow fits RetailVision — the plan

**Three experiments, two paths each** (comparison = vary the model; tuning = fix the
chosen model, vary one hyperparameter):

```
MLflow Tracking Server (http://localhost:5000)
│
├── Experiment: detection
│     ├── [comparison] yolov8n, yolov8x, yolo11x-seg, rtdetr-x   (× 2 videos each)
│     └── [tuning]     rtdetr-x @ conf={0.15, 0.30, 0.50}        (× 2 videos each)
│
├── Experiment: tracking
│     ├── [comparison] BoT-SORT, ByteTrack, OC-SORT, StrongSORT  (× 2 videos each)
│     └── [tuning]     BoT-SORT @ match_thresh={0.6,0.8,0.9}  → tag result=no_effect
│
└── Experiment: reid
      ├── [comparison] resnet50_msmt17, osnet_x1_0_msmt17, osnet_x1_0_market1501, osnet_x1_0(imagenet)
      └── [tuning]     chosen model @ reid_threshold={0.75,0.80,0.85,0.90}

(reconciliation: NOT an MLflow experiment — out of scope)
```

> **Gap 6 applied — run = (model × video).** Every comparison/tuning point runs on
> **both** your clips, producing two runs tagged `scene=mannequin` and
> `scene=crowded`. In the UI, filter `tags.scene = "mannequin"` to show RT-DETR's
> mannequin-rejection advantage; filter `crowded` to show recall in the cashier
> scene. Same work, far more insight.

**The storage stack reuses what you already run** — no new database technology:

```
your eval script ──logs──► MLflow Server :5000
                              ├── metadata (params/metrics)  → PostgreSQL  (a new `mlflow` DB)
                              └── artifacts (videos/plots)    → MinIO/S3   (a new `mlflow` bucket)
```

You already run PostgreSQL and MinIO for the main app. MLflow plugs straight into
both. That is the cleanest possible setup for this project.

---

## 4. Repo structure: the `mlops/` folder

All offline ML-lifecycle **code** lives in a new top-level `mlops/` folder. The
MLflow **server** is infra (a Compose service, stays in `docker-compose.dev.yml`
next to the postgres/minio it depends on). The teaching **docs** stay in `docs/`
so a grader finds all guides in one place. The rule: **`mlops/` may import from
`services/`, never the reverse — production never imports mlflow.**

```
retail-edge/
├── docker-compose.dev.yml          # EDIT: add the `mlflow` SERVER service (§6.1)
├── docs/
│   ├── MLFLOW_GUIDE.md             # this guide (stays in docs/)
│   └── docs_models/                # experiment FINDINGS (prose) — unchanged
│       ├── detection/  tracking/  reid/
└── mlops/                          # NEW — offline ML lifecycle (runnable code)
    ├── README.md                   # 10-line "how to run", links to this guide
    ├── requirements.txt            # mlflow, boto3, ultralytics, boxmot, opencv (EVAL-ONLY deps)
    ├── mlflow_utils.py             # tracking URI + log_run() helper (§8)
    ├── eval/
    │   ├── run_detection_eval.py   # detection comparison + conf tuning
    │   ├── run_tracking_eval.py    # tracker comparison + match_thresh sweep
    │   └── run_reid_eval.py        # reid comparison + threshold sweep
    ├── metrics/
    │   ├── detection_metrics.py    # unique_people, id_switches, count_error vs GT…
    │   ├── tracking_metrics.py     # fragmentation = unique_track_ids / N …
    │   └── reid_metrics.py         # reid_match_rate, false_merge_rate …
    └── labeling/
        └── labels.json             # ground truth: {"clip_cashier":{"total_people":12}, ...}
```

Your two clips go in `testing-data/` (alongside the existing Test1/Test2). The
**labels** live in `mlops/labeling/labels.json`. There is **no `mlruns/` folder** to
commit — you use the Postgres+MinIO backend, not local-file mode (add `mlruns/` to
`.gitignore` anyway, in case someone runs MLflow in file mode by accident).

> Why a separate `mlops/requirements.txt` (not a global one): production images must
> stay lean and must **not** be able to `import mlflow`; per-component requirements
> also match how every `services/*/Dockerfile` already installs deps and keep Docker
> build caching fast.

---

## 5. What to log per module (the metric lists)

Metrics taken **directly from your experiment docs**. Two buckets:
**programmable** (computed from pipeline output, no ground truth needed) and
**ground-truth** (need labels — see §11; add in Phase 1/2).

### 5.1 Detection (`experiment: detection`)

**Params:** `model`, `weights` (exact file, e.g. `rtdetr-x.pt`), `conf`, `imgsz`,
`iou`, `video`, `scene`, `class_filter=person`, `seed`, `frames_processed`.

**Programmable metrics (no ground truth):**

| Metric | Meaning |
|---|---|
| `unique_people` | Distinct people detected — headline proxy |
| `peak_count` | Max simultaneous people in one frame |
| `avg_confidence` | Mean detection confidence (%) |
| `avg_bbox_area` | Mean box area (px²) — tighter = better ReID crops |
| `id_switches` | Identity changes mid-track |
| `drop_to_zero` | Frames where count fell to 0 |
| `frames_processed` | Comparability check (should be equal across runs — Gap 1) |

**Ground-truth metrics (labels already known, §11):**

| Metric | Applies to | Formula | Good result |
|---|---|---|---|
| `count_error` | `scene=crowded` (clip_cashier) | `abs(unique_people − 16)` | →0 = found exactly the right number of people |
| `false_positive_total` | `scene=mannequin`/`hand_ad` (0-people clips) | total detections (every one is a false positive — 0 real people) | →0 = perfect rejection; the **graded** headline (detecting 2 ≪ detecting 6) |
| `false_positive_per_frame` | `scene=mannequin` | `false_positive_total / frames_processed` | →0; normalized companion so it compares fairly even if frame counts differ |

> **Why mannequin uses FP-count, not `count_error`:** clip_mannequin has **0 real
> people and 8 mannequins**, so the right metric isn't "how close to N people" — it's
> "how many false detections did the model make." `false_positive_total` is graded
> (fewer = better rejection); RT-DETR should approach 0 while YOLO variants won't.
> (`fp_object_count=8` is recorded so you can optionally also report distinct
> FP objects triggered out of N — see `fp_object_rejection_rate` in metrics.)

**Artifacts logged per run** (implemented in `mlops/eval/run_detection_eval.py`):
confidence-distribution histogram PNG; **5 annotated sample frames** (boxes drawn —
visual proof of false positives on a mannequin/hand-ad); `results.json` (params +
metrics + per-frame counts); `requirements.txt` (reproducibility). **System metrics**
(CPU/RAM) are auto-recorded for runs longer than the sampler interval (heavy models
qualify; the ~1 s yolov8n smoke run is too short to sample — expected).

### 5.2 Tracking (`experiment: tracking`)

Detection fixed at `rtdetr-x, conf=0.3, imgsz=640`.

**Params:** `tracker` (botsort/bytetrack/ocsort/strongsort), `match_thresh`,
`track_buffer`, `new_track_thresh`, `track_high_thresh`, `with_reid=False`,
`cmc_method=sof`, `frame_rate=5`, `video`, `scene`, `seed`, `frames_processed`.

**Programmable metrics:**

| Metric | Meaning |
|---|---|
| `unique_track_ids` | Distinct track IDs created — **primary tracker quality metric** (lower = less churn) |
| `id_switches` | track_id changes mid-track |
| `peak_count` | Max simultaneous confirmed tracks |
| `drop_to_zero` | Frames where confirmed count hit 0 |
| `per_frame_assoc_ms` | Association cost per frame (perf — you benchmarked ~4.18 ms) |
| `throughput_fps` | Tracker throughput (perf) |

**Ground-truth metrics (after labeling):** `fragmentation = unique_track_ids / total_people_GT` (1.0 = perfect; >1 = over-segmentation).

**Artifacts:** annotated clip showing track IDs; CSV of track lifetimes; `requirements.txt`.

### 5.3 ReID (`experiment: reid`)

Detection + tracking fixed (`rtdetr-x` + BoT-SORT defaults).

**Params:** `reid_model`, `weights` (exact file), `weights_dataset`
(imagenet/msmt17/market1501), `embedding_dim`, `reid_threshold`,
`sampling_interval`, `lost_pool_ttl`, `video`, `scene`, `seed`, `frames_processed`.

**Programmable metrics:**

| Metric | Meaning |
|---|---|
| `unique_people` | Distinct local_ids issued (inflation = false new IDs; deflation = wrong merges) |
| `id_switches` | local_id changes for the same physical person — primary ReID quality metric |
| `reid_match_rate` | Fraction of ReID lookups that recovered a prior identity |
| `reid_false_merge_rate` | Fraction of recoveries that wrongly merged two people (programmable if you track gallery vs recovered) |

**Ground-truth metrics (after labeling):** `count_error = |unique_people − total_people_GT|`.

**Artifacts:** matched-vs-mismatched gallery crops; similarity-score distribution plot; `requirements.txt`.

---

## 6. Answering your direct questions

### 6.1 Is MLflow its own Docker container?

**Yes — the MLflow *server* is one dedicated container** in `docker-compose.dev.yml`,
separate from everything else. The *client* (your `mlops/` eval scripts) is just
Python that talks to `http://localhost:5000`.

```yaml
  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.16.2
    command: >
      mlflow server
      --host 0.0.0.0 --port 5000
      --backend-store-uri postgresql://retailvision:retailvision_dev@postgres:5432/mlflow
      --artifacts-destination s3://mlflow
      --serve-artifacts
    ports:
      - "5000:5000"
    environment:
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: ${S3_ACCESS_KEY:-retailvision}
      AWS_SECRET_ACCESS_KEY: ${S3_SECRET_KEY:-retailvision_dev}
    depends_on:
      - postgres
      - minio
    restart: unless-stopped
```

### 6.2 Is MLflow related to Kubernetes?

**No.** Docker Compose only for this project. k8s is irrelevant to MLflow here.

### 6.3 How do I log, where does it go, where does the grader see it?

You add ~6 lines (`mlflow.log_param/metric/artifact`) in your `mlops/eval/` scripts.
Params/metrics land in **PostgreSQL** (`mlflow` DB); artifacts in **MinIO** (`mlflow`
bucket). The grader opens the **MLflow UI at http://localhost:5000**, picks an
experiment (`detection`/`tracking`/`reid`), ticks runs, clicks **Compare**. Data
persists in Docker volumes across restarts.

---

## 7. Step-by-step implementation (with Claude Code prompts)

> Use Claude Code for the heavy lifting. Each step has a **paste-ready prompt**.
> Effort: ~1 day total for all three experiments.

### Step 0 — Prerequisites
- Main stack runs: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres minio`
- Your two clips are in `testing-data/` as `clip_mannequin.mp4` and `clip_cashier.mp4`.

### Step 1 — Create the `mlops/` skeleton

**Claude Code prompt:**
> Create a top-level `mlops/` folder with this skeleton: `README.md` (10 lines:
> how to run evals, link to docs/MLFLOW_GUIDE.md), `requirements.txt` (mlflow,
> boto3, ultralytics, boxmot, opencv-python, numpy, pandas, matplotlib),
> `mlflow_utils.py` (a `log_run()` helper + tracking URI from env — see §8 of
> docs/MLFLOW_GUIDE.md), `eval/run_detection_eval.py`, `eval/run_tracking_eval.py`,
> `eval/run_reid_eval.py` (stubs with a `main()` and an argparse for which
> phase/video), `metrics/detection_metrics.py`, `metrics/tracking_metrics.py`,
> `metrics/reid_metrics.py` (pure functions computing the metrics in §5), and
> `labeling/labels.json` (empty `{}` for now). Add `mlruns/` to `.gitignore`.
> `mlops/` may import from `services/`, never the reverse — production must not
> import mlflow.

### Step 2 — Create MLflow's backend stores
```bash
docker compose exec postgres psql -U retailvision -c "CREATE DATABASE mlflow;"
# MinIO console http://localhost:9001 (retailvision/retailvision_dev) → create bucket: mlflow
```

### Step 3 — Add the MLflow server to Compose

**Claude Code prompt:**
> Add an `mlflow` service to `docker-compose.dev.yml` using the YAML in §6.1 of
> docs/MLFLOW_GUIDE.md (image ghcr.io/mlflow/mlflow:v2.16.2, backend-store-uri the
> `mlflow` Postgres DB, artifacts to s3://mlflow on MinIO, port 5000, depends_on
> postgres+minio). Don't change any other service.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d mlflow
# open http://localhost:5000 — empty UI
```

### Step 4 — Build the shared eval harness (process clip to completion)

**Claude Code prompt:**
> In `mlops/`, implement a shared evaluation harness used by all three eval scripts.
> Read `services/iep2_vision/detector/detector.py`, `tracker/tracker.py`, and
> `reid/reid.py` to reuse the real detection/tracking/ReID interfaces. The harness
> must: open a video file, run **every frame to completion** (never stop on a wall-
> clock timer — Gap 1), accumulate the §5 programmable metrics, and return them as a
> dict plus `frames_processed`. Set a fixed numpy/torch seed (default 42). It must
> NOT depend on Postgres/Redis — operate directly on the video file. Keep it CPU-
> friendly (these are 1-minute clips).

### Step 5 — Wire MLflow logging + reproducibility context (Gap 5)

**Claude Code prompt:**
> Implement `mlops/mlflow_utils.py` with `log_run(experiment, run_name, params,
> metrics, tags, artifacts)` that: sets the tracking URI from `MLFLOW_TRACKING_URI`
> (default http://localhost:5000), starts a run, logs params+metrics, sets tags, and
> logs artifacts. It must ALSO automatically, on every run: log `seed` as a param,
> set a `git_commit` tag from `git rev-parse HEAD`, and log the active
> `mlops/requirements.txt` as an artifact (Gap 5 reproducibility). Every caller must
> pass tags `phase` and `scene` and `metric_type`.

### Step 6 — Detection experiment (run the table in §10.1)

**Claude Code prompt:**
> Implement `mlops/eval/run_detection_eval.py`. It runs the detection experiment per
> §10.1 of docs/MLFLOW_GUIDE.md: comparison runs for models
> [yolov8n, yolov8x, yolo11x-seg, rtdetr-x] and tuning runs for rtdetr-x at
> conf [0.15, 0.30, 0.50] — each on BOTH videos (clip_mannequin → scene=mannequin,
> clip_cashier → scene=crowded), so run = (model × video). Use the Step-4 harness +
> Step-5 `log_run`. Log the §5.1 metrics. On scene=mannequin (0 real people, 8
> mannequins) ALSO log `false_positive_total` (count every detection — all are false
> positives) and `false_positive_per_frame`; on scene=crowded log `count_error` vs 16.
> Tag comparison runs phase=comparison, tuning runs phase=tuning; metric_type=proxy
> for raw metrics, labeled_count (cashier) / labeled_fp (mannequin) for GT metrics.
> run_name = `<model>_<conf>_<scene>`.

### Step 7 — Tracking experiment (run the table in §10.2)

**Claude Code prompt:**
> Implement `mlops/eval/run_tracking_eval.py`. Detection fixed at rtdetr-x conf=0.3.
> Comparison runs for trackers [botsort, bytetrack, ocsort, strongsort]; tuning runs
> for botsort at match_thresh [0.6, 0.8, 0.9] — each on BOTH videos. Read
> `services/iep2_vision/tracker/tracker.py` for the real BoT-SORT params
> (track_buffer=15, match_thresh=0.8, new_track_thresh=0.7, track_high_thresh=0.6,
> cmc_method=sof, frame_rate=5, with_reid=False). Log §5.2 metrics. If the
> match_thresh sweep shows no metric change, set tag `result=no_effect` on those
> runs. Tag phase/scene/metric_type. run_name = `<tracker>_mt<match_thresh>_<scene>`.

### Step 8 — ReID experiment (run the table in §10.3)

**Claude Code prompt:**
> Implement `mlops/eval/run_reid_eval.py`. Detection + tracking fixed. Comparison
> runs for reid models [resnet50_msmt17, osnet_x1_0_msmt17, osnet_x1_0_market1501,
> osnet_x1_0 (imagenet baseline)]; tuning runs for the chosen model at
> reid_threshold [0.75, 0.80, 0.85, 0.90] — each on BOTH videos. Read
> `services/iep2_vision/reid/reid.py` (EMBEDDING_DIM=2048) and the reid candidate
> table in docs/docs_models/reid/reid_experiments.md. Log §5.3 metrics + a
> similarity-score distribution plot artifact. Tag phase/scene/metric_type.

### Step 9 — Verify persistence
```bash
docker compose down && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d mlflow
# reopen http://localhost:5000 — all runs still there (proves Postgres+MinIO persistence)
```

### Step 10 — Ground-truth labeling (see §11) — Phase 1 first
Add `total_people` per clip to `mlops/labeling/labels.json`, then re-run (or extend)
the evals so each run also logs `count_error`. **Only after Phase 1 works**, add
Phase 2 per-frame counts.

### Step 11 — Document for the grader
Add a short "How to view results" note (§9) to your README / `mlops/README.md`.

---

## 8. The logging helper + example scripts

**`mlops/mlflow_utils.py`:**

```python
import os, subprocess
import mlflow

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "retailvision")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "retailvision_dev")
mlflow.set_tracking_uri(TRACKING_URI)

_REQUIREMENTS = os.path.join(os.path.dirname(__file__), "requirements.txt")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def log_run(experiment, run_name, params, metrics, tags=None, artifacts=None, seed=42):
    """Log one evaluation run with reproducibility context baked in (Gap 5)."""
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params({**params, "seed": seed})          # Gap 5: seed
        mlflow.set_tags({**(tags or {}), "git_commit": _git_commit()})  # Gap 5: commit
        mlflow.log_metrics(metrics)
        if os.path.exists(_REQUIREMENTS):
            mlflow.log_artifact(_REQUIREMENTS)               # Gap 5: pinned deps
        for path in (artifacts or []):
            mlflow.log_artifact(path)
```

**Example call (detection comparison, one video):**

```python
from mlflow_utils import log_run

metrics, frames = evaluate_detection("rtdetr-x.pt", conf=0.3, video="testing-data/clip_cashier.mp4")
log_run(
    experiment="detection",
    run_name="rtdetr-x_conf0.3_crowded",
    params={"model": "rtdetr-x", "weights": "rtdetr-x.pt", "conf": 0.3, "imgsz": 640,
            "video": "clip_cashier.mp4", "frames_processed": frames},
    tags={"phase": "comparison", "scene": "crowded", "metric_type": "proxy"},
    metrics=metrics,
    artifacts=["outputs/cashier_annotated.mp4"],
)
```

---

## 9. How the grader opens the results

Put this in your README / `mlops/README.md`:

> **Viewing the experiment results (MLflow)**
> 1. From `retail-edge/`: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres minio mlflow`
> 2. Open **http://localhost:5000**.
> 3. Pick an experiment: **detection**, **tracking**, or **reid**.
> 4. Tick two or more runs → **Compare** for side-by-side params/metrics/charts.
> 5. Filter: `tags.phase = "comparison"`, `tags.phase = "tuning"`, or `tags.scene = "mannequin"`.
> 6. Click a run → **Artifacts** to download annotated clips / plots.

---

## 10. The exact runs to execute (detection / tracking / reid)

> **Reminder (Gap 6):** every row below runs on **both** clips, producing two runs
> (`scene=mannequin` from `clip_mannequin.mp4`, `scene=crowded` from
> `clip_cashier.mp4`). So "4 comparison models" = **8 runs** (4 × 2 videos).

### 10.1 Detection

**Comparison runs** — `phase=comparison`, fixed `conf=0.3, imgsz=640`:

| # | model | weights file | conf | imgsz | videos |
|---|---|---|---|---|---|
| 1 | yolov8n | `yolov8n.pt` | 0.3 | 640 | both |
| 2 | yolov8x | `yolov8x.pt` | 0.3 | 640 | both |
| 3 | yolo11x-seg | `yolo11x-seg.pt` | 0.3 | 640 | both |
| 4 | rtdetr-x | `rtdetr-x.pt` | 0.3 | 640 | both |

**Tuning runs** — `phase=tuning`, fixed model `rtdetr-x`:

| # | model | conf | videos |
|---|---|---|---|
| 5 | rtdetr-x | 0.15 | both |
| 6 | rtdetr-x | 0.30 | both |
| 7 | rtdetr-x | 0.50 | both |

→ **7 rows × 2 videos = 14 detection runs.** (Weak baseline n / strong CNN x /
segmentation / transformer winner — exactly the spread your docs argue.)

**Metrics that matter:**
- On `scene=crowded` (clip_cashier, 16 people): `unique_people` (headline),
  `count_error = |unique_people − 16|`, `avg_confidence`, `avg_bbox_area`,
  `id_switches`, `peak_count`.
- On `scene=mannequin` (clip_mannequin, 0 people / 8 mannequins): `false_positive_total`
  (graded headline — every detection is a false positive) + `false_positive_per_frame`
  (normalized). RT-DETR should approach 0; YOLO variants won't — this is your
  strongest single comparison figure.
- Always: `frames_processed` (Gap 1 comparability).

### 10.2 Tracking

Detection fixed `rtdetr-x, conf=0.3`. **Comparison runs** — `phase=comparison`,
BoT-SORT defaults (`track_buffer=15, match_thresh=0.8, new_track_thresh=0.7,
track_high_thresh=0.6, cmc_method=sof, frame_rate=5, with_reid=False`):

| # | tracker | videos |
|---|---|---|
| 1 | botsort | both |
| 2 | bytetrack | both |
| 3 | ocsort | both |
| 4 | strongsort | both |

**Tuning runs** — `phase=tuning`, fixed `botsort`, 3-point `match_thresh` sweep:

| # | tracker | match_thresh | videos | note |
|---|---|---|---|---|
| 5 | botsort | 0.6 | both | tag `result=no_effect` if flat |
| 6 | botsort | 0.8 | both | baseline |
| 7 | botsort | 0.9 | both | tag `result=no_effect` if flat |

→ **7 rows × 2 videos = 14 tracking runs.** (Your docs show `match_thresh` is flat
— logging 3 points + `no_effect` is the honest, efficient way to prove it.)

**Metrics that matter:** `unique_track_ids` (primary — lower is better; docs show
BoT-SORT 29 vs ByteTrack 34 vs OC-SORT 51 vs StrongSORT 54), `id_switches`,
`peak_count`, `per_frame_assoc_ms`, `throughput_fps`. After labeling:
`fragmentation = unique_track_ids / total_people_GT`.

### 10.3 ReID

Detection + tracking fixed. **Comparison runs** — `phase=comparison`,
`reid_threshold=0.85`:

| # | reid_model | weights file | dataset | dim | videos |
|---|---|---|---|---|---|
| 1 | resnet50_msmt17 | `resnet50_msmt17.pt` | msmt17 | 2048 | both |
| 2 | osnet_x1_0_msmt17 | `osnet_x1_0_msmt17.pt` | msmt17 | 512 | both |
| 3 | osnet_x1_0_market1501 | `osnet_x1_0_market1501.pt` | market1501 | 512 | both |
| 4 | osnet_x1_0 (baseline) | `osnet_x1_0.pt` | imagenet | 512 | both |

**Tuning runs** — `phase=tuning`, fixed chosen model (start with `resnet50_msmt17`),
`reid_threshold` sweep:

| # | reid_threshold | videos |
|---|---|---|
| 5 | 0.75 | both |
| 6 | 0.80 | both |
| 7 | 0.85 | both |
| 8 | 0.90 | both |

→ **8 rows × 2 videos = 16 reid runs.** (Baseline imagenet = "wrong weights"
control; msmt17 vs market1501 = training-data fit; resnet50 vs osnet = architecture.)

**Metrics that matter:** `id_switches` (primary), `unique_people`, `reid_match_rate`,
`reid_false_merge_rate`. Plus the similarity-distribution plot for the threshold
sweep. After labeling: `count_error`.

> **Total across the three experiments: ~44 runs.** All scriptable; a single
> `python mlops/eval/run_*_eval.py` per experiment loops them.

---

## 11. Ground-truth labeling (phased) + the metrics it unlocks

"Annotation" here is **not a tool** — it's a few integers in a JSON file. You watch
each clip, count, and fill `mlops/labeling/labels.json`. Do Phase 1, confirm it
works, then optionally add Phase 2.

### How to annotate (the actual mechanics)

1. Open the clip, watch it, count.
2. Put the numbers in `mlops/labeling/labels.json`. That's the whole "annotation tool."
3. The evals read this file and compute the labeled metrics automatically.

### Phase 1 — already DONE (values you provided)

`mlops/labeling/labels.json` now holds your real ground truth:

```json
{
  "clip_mannequin.mp4": { "duration_s": 33, "total_people": 0, "fp_object_count": 8, "peak_people": 0 },
  "clip_cashier.mp4":   { "total_people": 16, "peak_people": 14, "per_frame": {} }
}
```

> **Two clips, two different ground-truth regimes:**
> - **clip_cashier** has **16 real people** (peak 14) → use **count accuracy**.
> - **clip_mannequin** has **0 real people and 8 mannequins** → every detection is a
>   false positive → use **false-positive count** (graded: detecting 2 ≪ detecting 6).

**Unlocks these real metrics:**

| Experiment | Clip / scene | Metric | Formula | Good result |
|---|---|---|---|---|
| detection | cashier (crowded) | `count_error` | `abs(unique_people − 16)` | →0 = exact people count |
| detection | cashier (crowded) | `peak_count_error` | `abs(peak_detected − 14)` | →0 = captured the busiest moment (14 at once) |
| detection | mannequin | `false_positive_total` | total detections (all are FPs) | →0 = perfect rejection (graded) |
| detection | mannequin | `false_positive_per_frame` | `false_positive_total / frames_processed` | →0; comparable across runs |
| tracking | cashier | `fragmentation` | `unique_track_ids / 16` | →1.0 ideal (e.g. BoT-SORT churn vs StrongSORT) |
| tracking | mannequin | `false_positive_total` (track IDs created) | count of tracks (all spurious) | →0 |
| reid | cashier | `count_error` | `abs(unique local_ids − 16)` | →0 = no false splits/merges |

Tag cashier runs `metric_type=labeled_count` and mannequin runs
`metric_type=labeled_fp` so the UI makes the two regimes obvious. (This is
count/FP accuracy, not full detection mAP — which would need per-box labels you are
NOT doing.)

> **Optional extra (cheap):** you can also report **distinct mannequins triggered out
> of 8** via `mannequin_rejection_rate = 1 − detected/8` (in
> `mlops/metrics/detection_metrics.py`) if your eval can attribute detections to
> distinct mannequins. Not required — `false_positive_total` is the headline.

**Claude Code prompt (Phase 1):**
> Add ground-truth support to the `mlops/` evals. Read `mlops/labeling/labels.json`.
> For each run, after computing programmable metrics, also compute and log the
> labeled metric appropriate to the clip:
> - If `total_people > 0` (clip_cashier=16): detection/reid `count_error =
>   abs(unique_people − total_people)`; tracking `fragmentation = unique_track_ids /
>   total_people`. Tag `metric_type=labeled_count`.
> - If `total_people == 0` and `fp_object_count > 0` (clip_mannequin): log
>   `false_positive_total` (every detection is a false positive) and
>   `false_positive_per_frame = false_positive_total / frames_processed`. Tag
>   `metric_type=labeled_fp`.
> Log `total_people` / `fp_object_count` as params. Use the helpers in
> `mlops/metrics/detection_metrics.py`. Skip gracefully if a clip has no label.

### Phase 2 — Per-frame people count on a few sampled frames (only after Phase 1)

Pick ~5–10 frames per clip (e.g. every 6 s), count people in each, store:

```json
{
  "clip_cashier.mp4": {
    "total_people": 12,
    "per_frame": { "0": 2, "300": 5, "600": 7, "900": 6, "1200": 4 }
  }
}
```

**Unlocks per-frame count accuracy for detection:** at each labeled frame compute
`abs(detected_count − gt_count)`; log `mean_per_frame_count_error` (MAE) over the
sampled frames. Tag `metric_type=labeled_perframe`.

**Claude Code prompt (Phase 2):**
> Extend the detection eval: for clips that have a `per_frame` map in
> `mlops/labeling/labels.json`, at each labeled frame index compute the absolute
> difference between detected person count and the labeled count, and log the mean
> as `mean_per_frame_count_error`. Tag those runs `metric_type=labeled_perframe`.
> Leave Phase-1 behavior unchanged.

---

## 12. Scope: why Tier 2 is the right amount

You are doing **detection + tracking + reid** (3 experiments), each with comparison
+ tuning, on 2 clips, with phased labeling. That is **Tier 2** — complete and
defensible without overdoing it.

**Why reconciliation is correctly excluded:** it's cross-camera, needs Postgres +
multiple synchronized inputs, and its quality metrics (correct vs wrong cross-camera
merges) need hand-labeled multi-camera ground truth you are not producing. It would
roughly double the effort for the weakest evidence. Leaving it out is the right call
— note it in your write-up as "future work."

**What stays out (true overkill):** auto-search frameworks (Optuna/Hyperopt),
MLflow Model Registry wiring into production, k8s deployment of MLflow, logging
per-frame data as step-metrics for every frame.

---

## 13. The minimal "enough" metric sets

4–6 metrics per experiment is plenty. One **primary** per experiment, the rest
supporting:

| Experiment | Primary | Supporting | Labeled (GT known) |
|---|---|---|---|
| detection | `unique_tracks` (crowded) / `false_positive_total` (mannequin) | `avg_confidence`, `avg_bbox_area`, `id_switches`, `peak_detections_per_frame` | `count_error` (vs 16), `false_positive_total`/`_per_frame`, later `mean_per_frame_count_error` |
| tracking | `unique_track_ids` | `id_switches`, `peak_count`, `per_frame_assoc_ms` | `fragmentation` (÷16) |
| reid | `id_switches` | `unique_people`, `reid_match_rate`, `reid_false_merge_rate` | `count_error` (vs 16) |

More metrics = a noisier Compare view, not better science.

---

## 14. Everything you should know to actually use MLflow

### 14.1 Install & connect
```bash
pip install -r mlops/requirements.txt
export MLFLOW_TRACKING_URI=http://localhost:5000   # PowerShell: $env:MLFLOW_TRACKING_URI="..."
```

### 14.2 Core logging API (the 95% you'll use)
```python
import mlflow
mlflow.set_experiment("detection")
with mlflow.start_run(run_name="rtdetr-x_conf0.3_crowded") as run:
    mlflow.log_param("model", "rtdetr-x")            # params are IMMUTABLE — set once
    mlflow.log_params({"conf": 0.3, "seed": 42})
    mlflow.set_tags({"phase": "comparison", "scene": "crowded", "metric_type": "proxy"})
    mlflow.log_metric("unique_people", 17)           # one number per run
    mlflow.log_artifact("outputs/clip.mp4")          # any file
    print("run_id:", run.info.run_id)
```
Rules: **one `start_run` = one row** (loop your sweep so each config is its own
run); params are immutable (log once); param/tag values are strings — keep them
short and consistent.

### 14.3 Reading results in the UI
- **Runs table:** one row per run; columns = params + metrics.
- **Search filters:** `tags.scene = "mannequin"`, `params.model = "rtdetr-x"`, `metrics.id_switches < 13`, combine with `and`.
- **Sort:** click a metric header (e.g. `unique_track_ids` ascending).
- **Compare:** tick ≥2 runs → **Compare** → parallel-coordinates + diff table.

### 14.4 Pulling results into your report (pandas)
```python
import mlflow
df = mlflow.search_runs(experiment_names=["detection"],
                        filter_string='tags.phase = "comparison"',
                        order_by=["metrics.unique_people DESC"])
print(df[["params.model", "params.scene", "metrics.unique_people", "metrics.mannequin_false_positives"]])
```
Generates your comparison tables directly from logged data — no hand-copying.

### 14.5 Where data lives
Params/metrics/tags → Postgres `mlflow` DB. Artifacts → MinIO `mlflow` bucket. UI →
the `mlflow` container on :5000. Survives `docker compose down` (named volumes).
**No `mlruns/` folder** in this setup.

### 14.6 Smoke test before real runs
```python
import mlflow
mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("smoke-test")
with mlflow.start_run(run_name="hello"):
    mlflow.log_param("x", 1); mlflow.log_metric("y", 2.0)
# open http://localhost:5000 → experiment 'smoke-test' → run 'hello', then delete it
```

---

## 15. Common mistakes & how to avoid them

| Mistake | Symptom | Fix |
|---|---|---|
| One `start_run` wrapping the whole sweep | all configs collapse into one row | one `with start_run()` **per config** |
| Stopping eval on a timer | runs see different frame counts | process clip to completion; log `frames_processed` (Gap 1) |
| Logging a param twice | `param already logged` error | params immutable; use metrics for changing values |
| Forgetting seed/weights/commit | run not reproducible | use `log_run()` which logs them automatically (Gap 5) |
| One run per model (no video split) | scene nuance hidden | run = (model × video), tag `scene` (Gap 6) |
| Calling proxy numbers "accuracy" | overstates result | tag `metric_type=proxy` until labeled |
| Artifacts fail to upload | `NoSuchBucket`/S3 error | create the `mlflow` MinIO bucket; check `MLFLOW_S3_ENDPOINT_URL` |
| Too many metrics | unreadable Compare view | 4–6 per experiment (§13) |

---

## 16. Final recommendation & end-to-end checklist

**Do Tier 2 and stop:** detection (4-model comparison + conf sweep), tracking
(4-tracker comparison + 3-point match_thresh sweep tagged `no_effect`), reid
(candidate-model comparison + reid_threshold sweep). Reconciliation: **skipped**.
Every run = (model × video) with `scene` tagged (Gap 6); each run logs
seed/weights/git_commit/requirements (Gap 5); each clip processed to completion
(Gap 1); 4–6 metrics each (§13); ground truth phased (Phase 1 total count, then
Phase 2 per-frame).

**Checklist:**
- [ ] `mlops/` skeleton created; `mlruns/` gitignored (Step 1)
- [ ] `mlflow` DB + MinIO bucket created (Step 2)
- [ ] `mlflow` server in `docker-compose.dev.yml`, UI loads on :5000 (Step 3)
- [ ] Shared harness processes clips to completion, fixed seed (Step 4)
- [ ] `log_run()` auto-logs seed + git_commit + requirements (Step 5)
- [ ] Detection 14 runs logged, tagged phase/scene/metric_type (Step 6, §10.1)
- [ ] Tracking 14 runs logged, flat sweep tagged `no_effect` (Step 7, §10.2)
- [ ] ReID 16 runs logged, similarity plot artifact (Step 8, §10.3)
- [ ] Persistence verified after `down`/`up` (Step 9)
- [ ] Phase-1 labels in `labels.json`; `count_error`/`fragmentation` logged (§11)
- [ ] (optional) Phase-2 per-frame labels + `mean_per_frame_count_error` (§11)
- [ ] "How to view results" note in README / `mlops/README.md` (Step 11)
```