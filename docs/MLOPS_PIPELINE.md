<!--
  Rubric: M1 — Automated lifecycle pipeline (2.5%), M2 — Experiment tracking and thresholds (2.5%)
-->

# MLOps pipeline — RetailVision

## 1. CI/CD pipeline (GitHub Actions)

**File:** `.github/workflows/ci.yml`

**Trigger:** Push to `main`, any pull request.

**Steps:**
1. Checkout code
2. Install dependencies
3. Run unit tests: `pytest tests/unit/`
4. Run integration tests: `pytest tests/e2e/` (with test fixtures, no live cloud)
5. Build Docker images (EEP, IEP3, IEP2)
6. TODO: Push images to registry on merge to main

**Status badge:** TODO (add GitHub Actions badge to README.md)

## 2. Experiment tracking (MLflow)

**Tracking server:** TODO (local MLflow server, or remote URI)

### Experiments logged

#### 2.1 YOLO variant selection
- **MLflow experiment:** `detection-model-selection`
- **Runs:** TODO (list run IDs or names)
- **Metrics tracked:** latency (ms/frame), mAP@0.5, GPU memory usage
- **Dataset:** TODO (test video clip used)
- **Winner:** TODO

#### 2.2 OSNet ReID variant selection
- **MLflow experiment:** `reid-model-selection`
- **Runs:** TODO (list run IDs or names)
- **Metrics tracked:** Rank-1 accuracy, embedding extraction time
- **Dataset:** TODO
- **Winner:** TODO

#### 2.3 Cosine similarity threshold sweep
- **MLflow experiment:** `reid-threshold-tuning`
- **Runs:** one run per threshold value (0.40, 0.50, 0.60, 0.70)
- **Metrics tracked:** precision, recall, false merge rate
- **Winner:** TODO (see TRADEOFFS.md §4)

## 3. Model promotion logic

A model version is promoted to production when ALL **applicable** thresholds below
hold. Thresholds are derived from the actual benchmark results in `docs_models/`
(the winning models: `rtdetr-x` for detection, `BoT-SORT` for tracking) and use the
exact MLflow metric keys logged by `mlops/eval/run_detection_eval.py`. The gate is
implemented in `scripts/check_promotion.py`.

> **Why these metrics and not mAP / FPS / Rank-1 accuracy?** Those were never
> measured in `docs_models/` — they were aspirational placeholders. The experiments
> recorded *proxy* metrics (confidence, ID switches, distinct counts, false
> positives). The gate only checks metrics that runs actually log; inventing
> missing ones would make every run report MISSING.

**Detection gate** (experiment `detection`):

| Metric | Threshold | Direction | Source | MLflow key |
|---|---|---|---|---|
| Avg detection confidence (%) | 86.0 | ≥ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 86.1%) | `avg_confidence` |
| ID switches | 12 | ≤ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 12, yolov8x = 16) | `id_switches` |
| Peak count error (scene=crowded) | 2 | ≤ | mlops/labeling/labels.json (GT = peak 14); validated by 21-run sweep (rtdetr-x/yolov8x/yolo11x-seg ≤1) | `peak_count_error` |
| False positives (scene=mannequin/hand_ad) | 0 | ≤ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 0 mannequin FP) | `false_positive_total` |

> **Why `count_error` (= |unique_tracks − 16|) is NOT a promotion gate:** the 21-run
> sweep showed it at 19–41 even for RT-DETR, but that is **tracking fragmentation**,
> not a detection failure — `unique_tracks` counts every track ID ever created, which
> inflates in a busy/occluded scene. RT-DETR's actual detection is excellent
> (`peak_detections_per_frame` = 13 vs true peak 14). Counting accuracy is therefore
> gated via `peak_count_error` (a per-frame detection metric), and track-ID inflation
> is a tracking-experiment concern, not a detection-gate one.

**ReID gate** (experiment `reid`) — ⚠️ PROXY (no identity ground truth; compares
models relatively, does not certify recovery correctness):

| Metric | Threshold | Direction | Source | MLflow key |
|---|---|---|---|---|
| Local-ID count error | 18 | ≤ | reid sweep (GT=16); resnet50/osnet_market pass, osnet_msmt17=39 fails | `count_error` |
| ReID match rate | 0.55 | ≥ | reid sweep; resnet50 0.60 / osnet_market 0.57 pass, osnet_msmt17 0.35 fails | `reid_match_rate` |

**Tracking gate** (experiment `tracking`) — detection FIXED at rtdetr-x conf0.5;
the gate is a *relative* bar that reproduces the ranking decision (PASS BoT-SORT,
FAIL StrongSORT), not an absolute-accuracy certificate:

| Metric | Threshold | Direction | Source | MLflow key |
|---|---|---|---|---|
| Track fragmentation (unique_track_ids / 16) | 4.0 | ≤ | tracking sweep; BoT-SORT 3.56 passes, OC-SORT 4.06 / ByteTrack 5.12 / StrongSORT 5.19 fail | `track_fragmentation` |
| ID switches | 12 | ≤ | tracking sweep; BoT-SORT 7 passes, StrongSORT 64 fails decisively | `id_switches` |

> `track_fragmentation` is the **primary** churn metric and the basis of the tracker
> decision; ≤4.0 isolates BoT-SORT as the only passing tracker. `id_switches` ≤12
> fails StrongSORT's 64 (≈9× the rest). Absolute counts are inflated (1810-frame /
> 3072×2048 clip) and inherit detection over-count — see TRACKING_RESULTS.md.

> The gate is **experiment-aware** (`scripts/check_promotion.py`
> `THRESHOLDS_BY_EXPERIMENT`): a `reid` run is checked against the reid thresholds, a
> `detection` run against the detection ones, a `tracking` run against the tracking
> ones — so `count_error` (= |local_ids−16|, reid) does not collide with the detection
> metric of the same name, and each experiment registers into its own model
> (`retailvision-detector` / `retailvision-tracker` / `retailvision-reid`).

**Scene applicability:** `false_positive_total` is only checked on 0-people clips
(`scene=mannequin`/`hand_ad`); `count_error`/`peak_count_error` only on
`scene=crowded`. The script skips non-applicable metrics so a run is not failed for
a metric that does not apply to its clip. ⚠️ Note `rtdetr-x` rejects 3-D mannequins
but not the 2-D printed hand-ad (Case 3), so a `hand_ad` run will fail the FP gate
by design — set per-scene expectations before promoting on that clip.

### Usage

```bash
# After logging a new MLflow experiment run:
python scripts/check_promotion.py --run-id <your-run-id>

# With a remote MLflow server:
python scripts/check_promotion.py --run-id <your-run-id> --tracking-uri http://your-mlflow-server:5000
```

### Promotion lifecycle (automated check → auto-register → human deploy)

The lifecycle separates **automated bookkeeping** from **human decisions**. The split
is deliberate: steps that change nothing live are automated; steps that designate or
deploy the live model require a human.

| Step | What it does | Automated? |
|---|---|---|
| **1. Promote (check)** | `check_promotion.py` evaluates a run's metrics vs thresholds → PROMOTE / DO NOT PROMOTE (exit 0/1) | ✅ automated check |
| **2. Register (Staging)** | On PROMOTE, opt-in `--register` creates a new version of `retailvision-detector` in **Staging** (`@candidate`) — pure catalog bookkeeping, nothing live changes | ✅ automated (opt-in) |
| **3. Production** | A human reviews the Staging candidate and sets it to **Production** | 🧍 human-in-the-loop |
| **4. Deploy** | A human updates the model reference in `services/iep2_vision/` + `services/yolo_service/` and restarts — only this changes what the live cameras run | 🧍 human-in-the-loop |

> **Why a human gate at steps 3–4:** registering to Staging is reversible metadata
> and safe to automate. Designating Production and deploying change reality, so a
> person signs off. A green gate is an *advisor*, not an auto-deploy.

**Commands:**
```bash
# 1. Run an experiment (logs runs to MLflow)
python mlops/eval/run_detection_eval.py

# 2. Check the gate only (no side effects):
python scripts/check_promotion.py --run-id <id>

# 2b. Check AND auto-register to Staging if it passes (opt-in):
python scripts/check_promotion.py --run-id <id> --register
#  -> creates retailvision-detector vN in Staging; Production untouched.

# 3-4. HUMAN: review the Staging version in the MLflow Models page, then (if approved)
#      set it to Production and update the model ref in the services + restart.
```

> **Note on CI:** the gate is run locally, not in GitHub Actions, because CI runs in
> the cloud and cannot reach the MLflow server on `localhost:5000`. The non-zero exit
> code makes it CI-scriptable later if MLflow is ever hosted reachably (future work).

> **Distinction — registered vs deployed:** "Production" in the MLflow registry is a
> *label*, not a deployment. The live edge pipeline loads the model its service code
> points at; it does not read the registry. Marking Production ≠ the cameras switching
> models — deployment (step 4) is what makes it live.

## Current promoted models

### Detection — `retailvision-detector` v1 (Production)
- **Model / config:** `rtdetr-x`, `conf=0.5`, `imgsz=640` (detection, crowded scene)
- **Run ID:** `7b4e10840bbe44848469faa667a6cf1d` (MLflow experiment `detection`, run `rtdetr-x_conf0.5_crowded`)
- **Registry:** `retailvision-detector` v1, stage=Production
- **Promoted on:** 2026-06-07 · **Promoted by:** Ali Zahreddine
- **Thresholds at promotion (all PASS):** `avg_confidence` 85.6 (≥75) · `id_switches` 7 (≤12) · `peak_count_error` 1 (≤2). Mannequin run = 0 false positives.
- **Why conf=0.5 over conf=0.3:** cleaner raw peak detection (13 vs true peak 14) and higher confidence; conf=0.3 over-detects via duplicate boxes (peak 18). Trade-off accepted: conf=0.5 has more ID switches (7 vs 1), but that is a tracking-stage concern.
- **Known limitation:** raw detection over-counts in crowds (duplicate/NMS-free boxes) and fails on the 2-D printed hand-ad (`hand_on_ad_in_store.mp4`, Case 3). True per-person counting happens downstream after ReID de-duplication in IEP3. Detection counts here are intentionally raw (no IoU dedup).

### ReID — `retailvision-reid` v1 (Production)
- **Model / config:** `resnet50_msmt17`, `reid_threshold=0.85` (the current production default)
- **Run ID:** `0aa5d06e8c4842928bc763c6709c9f58` (MLflow experiment `reid`, run `resnet50_msmt17_thr0.85_crowded`)
- **Registry:** `retailvision-reid` v1, stage=Production
- **Promoted on:** 2026-06-08 · **Promoted by:** Ali Zahreddine
- **Thresholds at promotion (all PASS, PROXY):** `count_error` 18 (≤18) · `reid_match_rate` 0.60 (≥0.55).
- **Why 0.85 (not the better-scoring 0.75):** the threshold sweep found 0.75 gives better *proxy* recovery (count_error 8, match_rate 0.71), but with **no identity ground truth** we can't confirm those extra recoveries aren't false merges. So 0.85 (current production) is promoted conservatively; **0.75 is a documented finding to validate with a labelled clip before adopting.**
- **Known limitation:** all reid metrics are **proxies** (no per-person identity labels) — they compare models relatively, not certified accuracy. See [REID_RESULTS](docs_models/reid/REID_RESULTS.md).

### Tracking — `retailvision-tracker` v1 (Production)
- **Model / config:** `BoT-SORT`, `match_thresh=0.8` (tracking, crowded scene; detection FIXED at rtdetr-x conf0.5)
- **Run ID:** `77881febe8fa437ca52605c5696a2722` (MLflow experiment `tracking`, run `botsort_mt0.8_crowded`)
- **Registry:** `retailvision-tracker` v1, stage=Production, alias `@production`
- **Promoted on:** 2026-06-08 · **Promoted by:** Ali Zahreddine
- **Thresholds at promotion (all PASS):** `track_fragmentation` 3.56 (≤4.0) · `id_switches` 7 (≤12). Lowest unique_track_ids (57) and fragmentation of the four trackers.
- **Why BoT-SORT over ByteTrack:** ByteTrack has fewer id_switches (5 vs 7) but ~44% more total tracks (82 vs 57 unique IDs) — BoT-SORT wins on the primary churn metric (identity continuity). Matches the production config in `services/iep2_vision/tracker/tracker.py`.
- **Known limitation:** absolute counts are inflated (longer/larger clip) and inherit detection over-count; the gate is a relative bar reproducing the ranking, not absolute accuracy. ~5–6× slower than ByteTrack (optical-flow CMC) — ByteTrack is the speed fallback if edge throughput becomes the constraint. See [TRACKING_RESULTS](docs_models/tracking/TRACKING_RESULTS.md).

## 4. Retraining trigger

Manual trigger: when the Prometheus `iep3_reid_cosine_score` average drops below TODO for more than 10 minutes, indicating potential model degradation.

**How to retrain:**
```bash
# TODO: fill in retraining command
```
