# Go-Live Runbook — deploying the merged robustness-qa features to EKS

This is the controlled, reversible procedure to put the merged code (Step 1 + the
"rest" + S2 autoscaling) onto the live EKS cluster. The file merge is already done on
the staging branch; the cluster still runs the **old images**, so nothing is live until
you complete the steps below.

**Golden rule:** the chart/infra topology was preserved as-is (deploy is canonical).
Going live = (1) build new images, (2) bump tags, (3) apply KEDA, (4) `helm upgrade`,
(5) validate, with rollback ready at every step.

---

## 0. Pre-flight
- [ ] Staging branch merged + all phase commits present (`git log --oneline`).
- [ ] `helm lint charts/retailvision` and `helm template charts/retailvision -f charts/retailvision/values.production.yaml` render clean (validates the IEP6 split + ScaledObject — could not be checked locally).
- [ ] `terraform plan` in `infra/aws` shows **only** the additive KEDA `helm_release` (+ `keda_version` var) — no changes to VPC/EKS/node-groups/Karpenter.
- [ ] Confirm a maintenance/low-traffic window; have the current image tags noted for rollback.

## 1. Build + push images (from merged code)
The merged app features only run once the cluster pulls **new images**.
- [ ] Trigger `.github/workflows/build-images.yml` (or build manually) for every changed service: `eep`, `iep1`–`iep5`, `iep6`, `frontend`, `reid`, `yolo`.
- [ ] **IEP6 must be rebuilt** — `main.py` + `requirements.txt` changed (the new `http_requests_inprogress` metric KEDA scales on lives in the image).
- [ ] Note the new tag (e.g. a git SHA or `1.4.0`). Images push as `ghcr.io/<owner>/retailvision/<service>:<tag>`.

## 2. Bump image tags
- [ ] In `charts/retailvision/values.yaml` (and `values.production.yaml` if it overrides), set each service's `image.tag` to the new build (eep, iep1-5, iep6, frontend, …). Current baseline is `1.3.0`.
- [ ] Commit the tag bump (deployment change — review it).

## 3. Apply KEDA (must precede helm — the ScaledObject needs the CRD)
```bash
cd infra/aws
terraform apply          # installs the KEDA operator + CRDs (keda.sh/v1alpha1)
kubectl get pods -n keda # operator/metrics-server/webhooks Running on the stable pool
kubectl get crd | grep keda.sh   # scaledobjects.keda.sh present
```
If you skip this, step 4 fails: the `ScaledObject` is an unknown kind without the CRD.

## 4. Helm upgrade
```bash
# DB migrations run via the chart's migrate-job (alembic upgrade head -> 0020).
helm upgrade retailvision charts/retailvision \
  -f charts/retailvision/values.production.yaml \
  --namespace retailvision --atomic --timeout 10m
```
`--atomic` auto-rolls-back the release if the upgrade fails.

## 5. Validate
**Migrations**
- [ ] `kubectl logs job/retailvision-migrate -n retailvision` → `alembic upgrade head` reached **0020** (agent tables present).

**Core services**
- [ ] `kubectl get deploy -n retailvision` → all Available; `frontend`, `eep` healthy.
- [ ] Frontend loads; log in as super-admin (`admin.vision@gmail.com`); Analytics / Live Monitoring / Store Setup / Alerts / Main Vision Debug render; a normal user does **not** see Main Vision Debug.
- [ ] EEP `/health` OK; rate-limiting active (429 on burst); a known endpoint returns the error envelope on bad input.

**IEP6 split + autoscaling (S2)**
- [ ] `kubectl get deploy -n retailvision | grep iep6` → **both** `iep6-agent` and `iep6-scheduler`; scheduler at **exactly 1**.
- [ ] `kubectl get deploy iep6-scheduler -o yaml | grep -A1 ENABLE_SCHEDULER` → `"true"`; `iep6-agent` → `"false"`. (Guards against duplicate scheduled insights/alerts + OpenAI spend.)
- [ ] `kubectl get scaledobject,hpa -n retailvision` → KEDA-managed HPA bound to `iep6-agent`.
- [ ] In Prometheus: `sum(http_requests_inprogress{app="iep6-agent"})` returns a series. **If the `app` label is absent**, fix the query in `keda-iep6-scaledobject.yaml` (relabel-dependent — flagged).
- [ ] Load-test the agent endpoint → `iep6-agent` scales up to `maxReplicas`; idle → back to `minReplicas`.

**Node scaling (S1 — already in place)**
- [ ] Activate a store (or simulate pipeline start) → IEP3/4 pods schedule on **Karpenter** nodes (not the `stable` pool); stopping → Karpenter consolidates (~1m).
- [ ] Stateful pods (postgres/redis/monitoring/mlflow) remain on the `stable` (tainted, on-demand) pool.

## 6. Rollback
- **Helm**: `helm rollback retailvision <PREV_REVISION> -n retailvision` (or rely on `--atomic`). `helm history retailvision -n retailvision` for revisions.
- **Images only**: revert the `image.tag` values to the previous tag + `helm upgrade`.
- **KEDA**: removing the ScaledObject (or `iep6.keda.enabled=false`) reverts IEP6 to fixed replicas; the operator can stay installed (inert without ScaledObjects). Full removal = `terraform destroy -target=helm_release.keda` (only if needed).
- **Migrations**: forward-only by policy; restore from DB backup if a schema rollback is ever required (do **not** auto-`downgrade` in prod).

## Notes / known verify-points
- Prometheus `app` label on the in-flight metric and the Prometheus service address (`http://prometheus.retailvision.svc:9090`) are the two things to confirm post-deploy for KEDA scaling.
- Charts/infra were intentionally left as deploy's (robustness-qa had nothing additive/safe there); the only deployment-topology change in this whole effort is the **IEP6 split + KEDA** (S2).
