<!--
  Rubric: M3 — Monitoring and ML-specific signals (2.5%)
-->

# Monitoring and observability — RetailVision

## 1. Prometheus metrics — per service

### EEP (control plane)

| Metric name | Type | Labels | Description |
|---|---|---|---|
| eep_request_duration_seconds | histogram | method, path, status | REST endpoint latency |
| eep_requests_total | counter | method, path, status | Request volume |
| eep_errors_total | counter | error_class | Errors by type |

### IEP2 (vision, per camera)

| Metric name | Type | Labels | Description |
|---|---|---|---|
| iep2_batch_duration_seconds | histogram | camera_id | Full vision batch time |
| iep2_detections_per_frame | histogram | camera_id | YOLO detection count |
| iep2_reid_extraction_seconds | histogram | camera_id | OSNet embedding time |

### IEP3 (reconciliation)

| Metric name | Type | Labels | Description |
|---|---|---|---|
| iep3_batch_duration_seconds | histogram | store_id | Reconciliation batch time |
| iep3_reid_cosine_score | histogram | store_id | **ML signal: ReID match score distribution** |
| iep3_global_identities_active | gauge | store_id | Live global identity count |
| iep3_false_merge_rate | gauge | store_id | TODO: how measured |
| iep3_windows_processed_total | counter | store_id | Total windows reconciled |

### Redis consumer lag

| Metric name | Type | Description |
|---|---|---|
| redis_stream_pending_entries | gauge | Pending messages per consumer group — indicates pipeline backpressure |

## 2. Grafana dashboard

**URL:** TODO: https://...

**Panels:**
1. EEP request latency (p50 / p95) — time series
2. EEP error rate — time series
3. IEP2 batch duration per camera — time series
4. IEP3 reconciliation latency — time series
5. **ReID cosine score distribution** — histogram panel (ML-specific signal)
6. Active global identities — gauge
7. Redis consumer lag — gauge
8. TODO: add more panels

## 3. ML-specific signal: ReID drift proxy

**Metric:** `iep3_reid_cosine_score` (histogram)

**What it measures:** The distribution of cosine similarity scores when IEP3 matches cross-camera embeddings. A healthy system shows scores clustered above the threshold. A degraded system shows the distribution shifting downward.

**What causes drift:**
- Lighting changes in the store (seasonal, time of day)
- New camera angles after store renovation
- Seasonal clothing changes (winter coats vs summer clothes)
- Camera hardware replacement with different optics

**Alert rule:** Average cosine score < TODO for more than 10 minutes → trigger alert.

**Alert destination:** TODO (Slack / PagerDuty / email)

## 4. Alerting rules

Prometheus alerting rules file: `monitoring/alert_rules.yml` (vendored into the
Helm chart at `charts/retailvision/files/alert_rules.yml`). On EKS, Prometheus +
Grafana run in-cluster on the stable pool; Grafana is exposed at
`grafana.<ingress-eip>.nip.io`. For the live deployment/operation of this stack see
**`docs/PROMETHEUS_GRAFANA_GUIDE.md`** — this file is the metrics/alerts design spec.

| Alert name | Condition | Severity | Action |
|---|---|---|---|
| HighEEPLatency | p95 > 2s for 5m | warning | TODO |
| IEP3BatchBacklog | consumer lag > 5 batches | warning | TODO |
| ReIDScoreDrop | avg cosine < TODO for 10m | warning | Retrain trigger |
| EdgeAgentOffline | heartbeat missing > 2m | critical | TODO |
