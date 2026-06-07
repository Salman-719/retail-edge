# Grading navigation guide — RetailVision

> This file tells the grader exactly where to find each rubric component.

## Quick links

| Rubric item | Criteria | File | Section |
|---|---|---|---|
| Architecture overview | GT3, T1 | ARCHITECTURE.md | Section 3 — End-to-End Diagram |
| AI pipeline depth & non-triviality | T1 | docs/AI_DEPTH.md | All |
| IEP1 independence & value | T2 | docs/services/IEP1_INGESTION.md | All |
| IEP2 independence & value | T3 | docs/services/IEP2_VISION.md | All |
| IEP3 reconciliation service | T3 | docs/services/IEP3_RECONCILIATION.md | All |
| EEP orchestration logic | T4 | docs/services/EEP_CONTROL_PLANE.md | All |
| Tradeoffs (≥3, with evidence) | T5 | docs/TRADEOFFS.md | All |
| Edge cases & failure modes | T6, S3 | docs/EDGE_CASES.md | All |
| Service contracts (schemas, protos, REST) | S1 | docs/SERVICE_CONTRACTS.md | All |
| Input validation & rate limits | S2 | docs/SECURITY.md | Section 1–2 |
| Error / retry / fallback behavior | S3 | docs/EDGE_CASES.md | Section 2 |
| Containerization & orchestration | S4 | docs/DEPLOYMENT.md | Section 2 |
| Deployment architecture | S5 | docs/DEPLOYMENT.md | Section 1 |
| Secrets management | S5 | docs/DEPLOYMENT.md | Section 3 |
| Cost estimate | S5 | docs/DEPLOYMENT.md | Section 4 |
| Problem statement | P1 | docs/POSITIONING.md | Section 1–2 |
| Non-AI baseline | P2 | docs/POSITIONING.md | Section 3 |
| AI justification | P3 | docs/POSITIONING.md | Section 4 |
| Real-world value & novelty | P4 | docs/POSITIONING.md | Section 5–6 |
| QA test suite (unit + integration + E2E) | Q1 | docs/qa/TEST_STRATEGY.md | All |
| Regression & golden dataset strategy | Q2 | docs/qa/REGRESSION_STRATEGY.md | All |
| CI/CD pipeline | M1 | docs/MLOPS_PIPELINE.md | Section 1 |
| Experiment tracking (MLflow) | M2 | docs/MLOPS_PIPELINE.md | Section 2 |
| Model promotion thresholds | M2 | docs/MLOPS_PIPELINE.md | Section 3 |
| Prometheus metrics per service | M3 | docs/MONITORING.md | Section 1 |
| ML-specific signal (ReID drift proxy) | M3 | docs/MONITORING.md | Section 3 |
| Grafana dashboard | M3 | docs/MONITORING.md | Section 2 |
| Full documentation completeness | M4 | This file |
| Key design decisions | T5, S3 | docs/decisions/ | All ADRs |
| Privacy & ethics | P4 | docs/PRIVACY_ETHICS.md | All |

## Live deployment
- API base URL: `TODO: https://...`
- Grafana dashboard: `TODO: https://...`
- GitHub repo: `TODO: https://...`

## How to run the tests
```bash
# All tests
pytest tests/

# Unit only (no infra required)
pytest tests/unit/

# End-to-end against live cloud deployment
pytest tests/e2e/ --cloud
```
