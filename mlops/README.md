# mlops/ — Offline ML lifecycle (MLflow experiments)

Eval, model comparison, and hyperparameter tuning for **detection**, **tracking**,
and **reid**, logged to MLflow. This is **offline** tooling — it never runs in the
production pipeline, and production code never imports anything here.

> Full guide: [`docs/MLFLOW_GUIDE.md`](../docs/MLFLOW_GUIDE.md)

## Quick start

```bash
# 1. Bring up infra + the MLflow server
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres minio mlflow

# 2. Install eval deps (eval-only — NOT installed in production images)
pip install -r mlops/requirements.txt
export MLFLOW_TRACKING_URI=http://localhost:5000

# 3. Run an experiment (each loops its runs over both clips)
python mlops/eval/run_detection_eval.py
python mlops/eval/run_tracking_eval.py
python mlops/eval/run_reid_eval.py

# 4. View results
open http://localhost:5000        # experiments: detection / tracking / reid
```

## Layout

```
mlops/
├── requirements.txt        # mlflow, boto3, ultralytics, boxmot, opencv… (eval-only)
├── mlflow_utils.py         # log_run() — auto-logs seed, git_commit, requirements.txt
├── eval/                   # one runner per experiment
├── metrics/                # pure metric functions (no ground truth needed + labeled ones)
└── labeling/labels.json    # ground truth (Phase 1: total_people; Phase 2: per_frame)
```

## Rules
- `mlops/` may import from `services/`; **`services/` must never import from `mlops/`** (production must not depend on mlflow).
- Videos live in `testing-data/`; only the **labels** live here.
- Every run is `(model × video)` and tagged `phase` / `scene` / `metric_type`.
- Clips are processed **to completion** (never stopped on a timer).
