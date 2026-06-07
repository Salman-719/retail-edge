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

| Metric | Threshold | Direction | Source | MLflow key |
|---|---|---|---|---|
| Avg detection confidence (%) | 86.0 | ≥ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 86.1%) | `avg_confidence` |
| ID switches | 12 | ≤ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 12, yolov8x = 16) | `id_switches` |
| People count error (scene=crowded) | 2 | ≤ | mlops/labeling/labels.json (GT = 16 people) — ⚠️ tolerance is an estimate | `count_error` |
| Peak count error (scene=crowded) | 2 | ≤ | mlops/labeling/labels.json (GT = peak 14) — ⚠️ tolerance is an estimate | `peak_count_error` |
| False positives (scene=mannequin/hand_ad) | 0 | ≤ | docs_models/detection/detection_experiments.md (Round 4: rtdetr-x = 0 mannequin FP) | `false_positive_total` |

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

### Promotion process (manual gate)

Promotion is a **manual checkpoint**, run locally before a model is deployed — it is
deliberately not wired into GitHub Actions, because CI runs in the cloud and cannot
reach the MLflow server running on `localhost:5000`. The gate is the human
decision step, not an auto-deploy:

1. Run an experiment — `python mlops/eval/run_detection_eval.py` (logs runs to MLflow).
2. Find the run in the MLflow UI (http://localhost:5000) and copy its run ID.
3. Run the gate — `python scripts/check_promotion.py --run-id <id>`.
   - **Exit 0 / "PROMOTE"** → proceed to step 4.
   - **Exit 1 / "DO NOT PROMOTE"** → tune hyperparameters and re-run.
4. On PROMOTE: update the model reference in `services/iep2_vision/` and
   `services/iep3_reconciliation/`, then record the run below in
   **Current promoted model**.

The non-zero exit code makes this scriptable later if the MLflow server is ever
hosted somewhere CI can reach (see TRADEOFFS / future work).

## Current promoted model
- **Run ID:** TODO — paste the MLflow run ID of the currently deployed model
- **Promoted on:** TODO — date
- **Promoted by:** TODO — team member name
- **All thresholds at promotion:** see MLflow run linked above

## 4. Retraining trigger

Manual trigger: when the Prometheus `iep3_reid_cosine_score` average drops below TODO for more than 10 minutes, indicating potential model degradation.

**How to retrain:**
```bash
# TODO: fill in retraining command
```
