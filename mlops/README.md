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
├── check_state.py          # validates MLflow promotion/canary state
├── canary_eval.py          # evaluates Prometheus canary/platform metrics
├── compare_shadow.py       # compares shadow-mode results from MLflow/fallback JSONL
├── promote.py              # MLflow registry transition helpers
├── run_promotion.py        # manual promotion ladder orchestrator
└── labeling/labels.json    # ground truth (Phase 1: total_people; Phase 2: per_frame)
```

## EKS MLOps access

```bash
kubectl -n retailvision port-forward svc/prometheus 9090:9090
export PROMETHEUS_URL=http://localhost:9090
export MLFLOW_TRACKING_URI=https://mlflow.$INGRESS_EIP.nip.io

python -m venv .venv-mlops
. .venv-mlops/bin/activate
pip install -r mlops/requirements.txt

python mlops/check_state.py --model-name retailvision
python mlops/canary_eval.py
python mlops/run_promotion.py --model-name retailvision --dry-run
```

Canary traffic is a Helm value on EEP:

```bash
helm upgrade retailvision ./charts/retailvision -n retailvision --reuse-values \
  --set eep.canaryPercentage=10
```

Reset canary:

```bash
helm upgrade retailvision ./charts/retailvision -n retailvision --reuse-values \
  --set eep.canaryPercentage=0
```

## Rules
- `mlops/` may import from `services/`; **`services/` must never import from `mlops/`** (production must not depend on mlflow).
- Videos live in `testing-data/`; only the **labels** live here.
- Every run is `(model × video)` and tagged `phase` / `scene` / `metric_type`.
- Clips are processed **to completion** (never stopped on a timer).
