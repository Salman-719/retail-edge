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

A model version is promoted to production when ALL of the following hold:

| Metric | Threshold | Source |
|---|---|---|
| ReID Rank-1 accuracy | ≥ TODO% | MLflow run |
| IEP2 frame latency (p95) | ≤ TODO ms | MLflow run |
| False merge rate | ≤ TODO% | MLflow run |

**Decision record:** TODO (link to the MLflow run that was promoted, or the PR that updated the model)

## 4. Retraining trigger

Manual trigger: when the Prometheus `iep3_reid_cosine_score` average drops below TODO for more than 10 minutes, indicating potential model degradation.

**How to retrain:**
```bash
# TODO: fill in retraining command
```
