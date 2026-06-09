# RetailVision Observability

RetailVision uses Prometheus, Grafana, Alertmanager, and MLflow for production
observability and offline model lifecycle work.

## Deployment Shape

- Cloud EKS Helm chart deploys Prometheus, Grafana, Alertmanager, exporters, and
  MLflow when `monitoring.enabled=true` and `mlflow.enabled=true`.
- Prometheus is internal `ClusterIP`; access it with `kubectl port-forward`.
- Grafana and MLflow can be exposed through the existing ingress using
  `monitoring.grafana.host` and `mlflow.host`.
- IEP3 pods are scraped through Kubernetes pod discovery annotations.
- Edge IEP1, IEP2, YOLO, and ReID expose metrics ports, but the current default
  deployment does not run a cloud-to-edge federation job. Use edge port-forward
  for local inspection, or add WireGuard-reachable scrape targets later.

## Access

```bash
kubectl -n retailvision port-forward svc/prometheus 9090:9090
kubectl -n retailvision port-forward svc/grafana 3000:3000
kubectl -n retailvision port-forward svc/mlflow 5000:5000
```

Grafana admin password:

```bash
kubectl -n retailvision get secret retailvision-secrets \
  -o jsonpath='{.data.grafana-admin-password}' | base64 -d; echo
```

## Dashboards

Helm provisions dashboards from:

- `charts/retailvision/files/grafana/dashboards/`
- source copies live under `monitoring/grafana/provisioning/dashboards/`

Main dashboards:

- `overview.json`
- `stream-health.json`
- `inference-latency.json`
- `tracker.json`
- `reconciliation.json`
- `business.json`
- `postgres.json`
- `mlflow.json`

## Metrics

Cloud:

- EEP `/metrics`: FastAPI HTTP metrics plus `eep_active_cameras`,
  `eep_scheduler_ticks_total`, `eep_grpc_connections_active`, and
  `eep_requests_total{model_version=...}` for canary split visibility.
- IEP3 `:9300`: batch timing, camera reporting count, identity transitions,
  match/new identity counters, appearance-fallback cosine, and match-rate gauge.
- Redis/Postgres/node exporters are chart-managed.

Edge:

- IEP1 `:9200`: frame capture/drop/encode and manifest publish latency.
- IEP2 `:9201`: per-camera frame latency, detections, confidence, active tracks,
  track age, and identity-switch proxy.
- YOLO `:9400`: detector frames, detections, latency, batch size, confidence.
- ReID `:9401`: crops, latency, batch size, raw embedding norm.

## Alerts

Prometheus loads:

- `charts/retailvision/files/alert_rules.yml`
- `charts/retailvision/files/recording_rules.yml`

Alertmanager is deployed with a safe null receiver by default. Configure a real
receiver through Kubernetes/AWS Secrets before relying on notifications.

## MLOps

MLflow runs in-cluster and stores artifacts in S3. Offline experiment tools live
in `mlops/` and are intentionally separate from production service images.

Manual production access:

```bash
export MLFLOW_TRACKING_URI="https://mlflow.$INGRESS_EIP.nip.io"
export PROMETHEUS_URL="http://localhost:9090"
kubectl -n retailvision port-forward svc/prometheus 9090:9090
python -m venv .venv-mlops
. .venv-mlops/bin/activate
pip install -r mlops/requirements.txt
python mlops/check_state.py --model-name retailvision
```
