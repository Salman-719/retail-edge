# CI/CD Secrets Reference

The current production path is EKS + Helm. CI is responsible for building GHCR
images and optional offline MLOps checks; Terraform/Helm deployment is still run
explicitly from the operator shell or CloudShell.

## Required For Image Publishing

| Secret | Scope | Purpose |
|---|---|---|
| `REGISTRY_USERNAME` | repository | GitHub user or machine account with GHCR package access |
| `REGISTRY_PASSWORD` | repository | GitHub PAT with `write:packages` |

Images are pushed as:

```text
ghcr.io/<owner>/retailvision/<service>:<tag>
```

The production Helm chart pulls `eep`, `frontend`, `iep3`, `iep4`, `iep5`,
`iep6`, and `mlflow`. These packages must be public or the cluster must be given
an image pull secret.

## Optional MLOps Variables

Use these for manual promotion/evaluation jobs or future CI workflows:

| Variable/Secret | Purpose |
|---|---|
| `MLFLOW_TRACKING_URI` | MLflow tracking server URL |
| `PROMETHEUS_URL` | Prometheus URL used by `mlops/canary_eval.py` |
| `PROMOTION_MODEL_NAME` | MLflow registered model name, default `retailvision` |
| `CANARY_PERCENTAGE` | EEP request canary split percentage |
| `SHADOW_WINDOW_SECONDS` | Shadow comparison window |
| `CANARY_WINDOW_SECONDS` | Canary evaluation window |

For EKS, prefer running MLOps commands from CloudShell or a machine with
`kubectl` access and port-forward Prometheus when needed:

```bash
kubectl -n retailvision port-forward svc/prometheus 9090:9090
export PROMETHEUS_URL=http://localhost:9090
export MLFLOW_TRACKING_URI=https://mlflow.$INGRESS_EIP.nip.io
python mlops/check_state.py --model-name retailvision
```

## AWS Runtime Secrets

Runtime app secrets are not stored in GitHub Actions. They live in AWS Secrets
Manager and are synced into Kubernetes by External Secrets:

- `retailvision/postgres-password`
- `retailvision/redis-password`
- `retailvision/jwt-secret`
- `retailvision/agent-secret`
- `retailvision/redis-url`
- `retailvision/s3-access-key`
- `retailvision/s3-secret-key`
- `retailvision/openai-api-key`
- `retailvision/grafana-admin-password`

Terraform creates or references these during EKS provisioning. Do not hard-code
notification tokens, Grafana passwords, or cloud credentials into monitoring
files.
