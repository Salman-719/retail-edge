# Milestone 7: MLOps Pipeline

**Duration:** 1 week
**Dependencies:** M3
**Goal:** ReID fine-tuning pipeline with MLflow tracking, golden dataset evaluation, and model promotion/rollback.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| MLflow server | NOT STARTED | |
| Golden dataset | NOT STARTED | |
| Data collection pipeline | NOT STARTED | |
| Fine-tuning script | NOT STARTED | |
| Evaluation script | NOT STARTED | |
| Promotion logic | NOT STARTED | |
| Rollback logic | NOT STARTED | |
| Pipeline trigger | NOT STARTED | |

**Overall: 0% complete**

---

## Implementation Tasks

### 1. Deploy MLflow Server

**File:** `docker-compose.yml` — add MLflow service:

```yaml
mlflow:
  image: ghcr.io/mlflow/mlflow:v2.14.0
  ports:
    - "5000:5000"
  environment:
    MLFLOW_BACKEND_STORE_URI: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/mlflow
    MLFLOW_DEFAULT_ARTIFACT_ROOT: s3://retailvision/mlflow-artifacts
    AWS_ACCESS_KEY_ID: ${S3_ACCESS_KEY}
    AWS_SECRET_ACCESS_KEY: ${S3_SECRET_KEY}
    MLFLOW_S3_ENDPOINT_URL: http://minio:9000
  command: mlflow server --host 0.0.0.0 --port 5000
  depends_on:
    postgres:
      condition: service_healthy
```

Create `mlflow` database in PostgreSQL init script.

### 2. Golden Dataset

**Directory:** `services/iep2-vision/data/golden/` (NEW)

```
Structure:
  golden/
    README.md          -- dataset description, collection date, ground truth
    images/
      employee_001/    -- 20-30 crops of employee 1
        crop_001.jpg
        crop_002.jpg
      employee_002/
        ...
      customer_001/    -- negative examples
        ...
    metadata.json      -- {employee_id: [image_paths], ...}

Rules:
  - NEVER include golden dataset in training data
  - Minimum 20 crops per employee from different cameras/angles
  - Include varied lighting, poses, partial occlusion
  - Store in S3: s3://retailvision/datasets/golden/v1/
```

### 3. Data Collection Pipeline

**File:** `services/iep2-vision/app/utils/data_collector.py` (NEW)

```python
class ReIDDataCollector:
    """Accumulate high-confidence employee crops during normal operation."""

    CONFIDENCE_THRESHOLD = 0.85  # only collect high-confidence matches
    MIN_CROP_SIZE = (64, 128)    # minimum pixel dimensions
    MAX_PER_EMPLOYEE = 500       # cap to prevent imbalance

    def collect(self, crop, employee_id, confidence, camera_id):
        """Save crop if passes quality checks.

        1. Check confidence > threshold
        2. Check crop dimensions > minimum
        3. Check not blurry (Laplacian variance)
        4. Save to S3: datasets/training/{version}/employee_{id}/
        5. Update dataset manifest in Redis
        """

    def get_dataset_stats(self) -> dict:
        """Return {employee_id: crop_count} for current version."""

    def should_trigger_training(self) -> bool:
        """Return True if N new samples collected since last training."""
```

### 4. Fine-Tuning Script

**File:** `services/iep2-vision/training/finetune_reid.py` (NEW)

```python
"""ReID model fine-tuning with MLflow tracking.

Usage:
  python finetune_reid.py \
    --base-model osnet_x1_0 \
    --dataset-version v3 \
    --epochs 30 \
    --lr 0.0003 \
    --batch-size 32
"""
import mlflow
import torchreid

def finetune(args):
    mlflow.set_experiment("reid-finetuning")

    with mlflow.start_run():
        # Log parameters
        mlflow.log_params({
            "base_model": args.base_model,
            "dataset_version": args.dataset_version,
            "epochs": args.epochs,
            "learning_rate": args.lr,
            "batch_size": args.batch_size,
            "loss": "triplet + cross_entropy_label_smooth",
        })

        # Load dataset from S3
        dataset = load_dataset(args.dataset_version)

        # Initialize model
        model = torchreid.models.build_model(
            name=args.base_model,
            num_classes=dataset.num_classes,
            pretrained=True
        )

        # Train
        engine = torchreid.engine.ImageTripletEngine(...)
        for epoch in range(args.epochs):
            metrics = engine.train_one_epoch()
            mlflow.log_metrics(metrics, step=epoch)

        # Save model artifact
        mlflow.pytorch.log_model(model, "reid_model")
        mlflow.log_artifact("training_curves.png")

    return model
```

### 5. Evaluation Script

**File:** `services/iep2-vision/training/evaluate_reid.py` (NEW)

```python
"""Evaluate ReID model on golden dataset.

Metrics:
  - Rank-1 accuracy: correct match in top-1 retrieval
  - mAP: mean average precision across all queries
  - CMC curve: cumulative matching characteristic
  - Per-employee accuracy: detect regressions on individual employees
"""
import mlflow

def evaluate(model_path, golden_path):
    mlflow.set_experiment("reid-evaluation")

    with mlflow.start_run():
        model = load_model(model_path)
        gallery, queries = load_golden_dataset(golden_path)

        # Extract embeddings
        gallery_embs = extract_all(model, gallery)
        query_embs = extract_all(model, queries)

        # Compute metrics
        rank1 = compute_rank1(query_embs, gallery_embs)
        mAP = compute_map(query_embs, gallery_embs)
        per_employee = compute_per_employee(query_embs, gallery_embs)

        mlflow.log_metrics({"rank1": rank1, "mAP": mAP})
        mlflow.log_dict(per_employee, "per_employee_accuracy.json")

        # Log CMC curve plot
        plot_cmc(query_embs, gallery_embs)
        mlflow.log_artifact("cmc_curve.png")

    return {"rank1": rank1, "mAP": mAP, "per_employee": per_employee}
```

### 6. Promotion Logic

**File:** `services/iep2-vision/training/promote.py` (NEW)

```python
def should_promote(new_metrics, current_metrics) -> bool:
    """Decide whether to promote new model to production.

    Criteria:
    1. Rank-1 improves by > 1% (absolute)
    2. mAP does not degrade by > 0.5%
    3. No individual employee regresses by > 5%

    If all criteria met:
    - Register model in MLflow Model Registry as new version
    - Transition current 'Production' to 'Archived'
    - Transition new version to 'Production'
    - Update model path in IEP2 config (Redis or env)
    """

def promote(run_id):
    client = mlflow.tracking.MlflowClient()
    model_uri = f"runs:/{run_id}/reid_model"
    mv = client.create_model_version("reid-production", model_uri, run_id)
    client.transition_model_version_stage("reid-production", mv.version, "Production")
```

### 7. Rollback Logic

**File:** `services/iep2-vision/training/rollback.py` (NEW)

```python
def check_rollback_needed() -> bool:
    """Monitor ReID distance distribution in production.

    Prometheus metric: reid_cosine_distance (histogram)
    Check: If mean distance shifts by > 2 std deviations from baseline
           for > 10 minutes, trigger rollback.
    """

def rollback():
    """Revert to previous MLflow model version.

    1. Get current 'Production' version
    2. Get previous 'Archived' version
    3. Swap stages
    4. Notify IEP2 to reload model (via Redis pub/sub or API call)
    5. Log rollback event
    """
```

### 8. Pipeline Trigger

**File:** `services/iep2-vision/app/api/mlops.py` (NEW)

```python
POST /mlops/train
  Input: {dataset_version: str, epochs: int, lr: float}
  Process: Submit training job (background task)
  Output: {job_id, status: "submitted"}

POST /mlops/evaluate
  Input: {model_run_id: str}
  Process: Evaluate against golden dataset
  Output: {rank1, mAP, per_employee}

POST /mlops/promote
  Input: {run_id: str}
  Process: Check criteria and promote if met
  Output: {promoted: bool, reason: str}

GET /mlops/status
  Output: {current_model, version, last_trained, metrics}
```

Auto-trigger: check `should_trigger_training()` after each tracking job in `tracker.py`.

---

## Evaluation Criteria (must pass before M8)

- [ ] MLflow UI accessible and shows experiment runs
- [ ] Fine-tuning produces a model that performs differently than baseline
- [ ] Golden dataset evaluation produces consistent, reproducible metrics
- [ ] Promotion only happens when criteria are met
- [ ] Rollback fires on simulated metric degradation
- [ ] Model Registry shows version history
- [ ] All tests pass

## Re-iteration Triggers

- If fine-tuning degrades model: lower learning rate, check data quality, remove mislabeled crops
- If golden dataset too small: augment with flips/color jitter, collect more enrollment data
- If rollback too sensitive: increase threshold or time window
