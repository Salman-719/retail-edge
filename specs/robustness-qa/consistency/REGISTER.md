# Consistency Register

Living catalogue of cross-cutting inconsistencies found by the scans in
[00-PLAN.md](00-PLAN.md). Each entry: what, where, the canonical truth, severity,
fix, and the guardrail that keeps it fixed. Re-run the scans after code churn and
append/close entries.

Status legend: OPEN · GUARDED (a CI check now prevents recurrence) · CLOSED.

---

## CONS-001 — Embedding dimension / byte-length  ·  Class A  ·  GUARDED

**Concept:** the ReID embedding size, declared in several places.
**Sites:** `services/reid_service/service.py` `EMBEDDING_DIM=2048`;
`services/iep2_vision/reid/reid.py` `EMBEDDING_DIM=2048`;
`services/iep3_reconciliation/app/settings.py` `embedding_dim=2048`;
`services/eep/schema.sql` "float32[2048] … 8192 bytes"; Alembic
`0005_embedding_dim_2048.py` re-adds the centroid `octet_length` CHECK at 8192.
**Finding:** all sites AGREE — 2048-dim × 4 bytes = 8192 bytes. Migration
`0002_constraints.py` still shows `octet_length(centroid) = 2048`, but that is
correct *history* (the OSNet 512-dim era = 2048 bytes); `0005` supersedes it at
runtime. Migrations are append-only — do NOT edit 0002.
**Canonical truth:** 2048-dim, 8192 bytes. **Severity:** low (currently consistent).
**Fix:** none needed. **Guardrail:** G1 — a CI test asserts reid/iep2/iep3 dims
agree and dim×4 equals the live schema byte constraint, so a future model swap
that changes one place fails CI until all agree. (Implemented:
`tests/unit/consistency/test_consistency.py`.)

## CONS-002 — `camera_id` vs `camera-id` pod label  ·  Class C  ·  OPEN

**Concept:** the per-camera identifier as a k8s pod label.
**Sites:** `services/edge_agent/app/k8s_manager.py` — the IEP2 pod template carries
BOTH `"camera-id"` (hyphen, the app's canonical label, read back at lines 251/273/275)
AND `"camera_id"` (underscore, added by the mlops-observability merge for Prometheus
relabeling), plus `"store_id"`.
**Finding:** the same concept under two label keys. Both are additive metadata
(no runtime effect); the underscore form feeds Prometheus pod relabeling, the hyphen
form is what the Edge Agent reads.
**Canonical truth:** `camera-id` is the app label; `camera_id`/`store_id` exist only
for Prometheus relabeling. **Severity:** low. **Fix:** keep both but document the split
in `k8s_manager` (a comment) so neither is "cleaned up" by mistake; OR add a Prometheus
`metric_relabel_configs` to map `camera-id`→`camera_id` and drop the duplicate label.
Decision deferred to the observability owner. **Guardrail:** none yet (would need a
k8s-manifest lint).

## CONS-003 — Removed concept `section_id`  ·  Class E  ·  GUARDED

**Concept:** the deleted `sections` layer (SPEC-00A).
**Finding:** `section_id` appears ONLY in `0009_remove_sections.py` (the migration that
removed it) — not reintroduced in any model/router. Clean.
**Canonical truth:** sections are permanently gone (see project memory). **Severity:**
high IF reintroduced (would resurrect dead schema). **Guardrail:** G5 — a CI test greps
`services/**/app/models` + routers for `section_id`/`section_ids` and fails if found.
(Implemented.)

## CONS-004 — Coordinate units (px vs m)  ·  Class B  ·  OPEN

**Concept:** spatial fields carry different physical units with no naming rule.
**Sites (representative):** `floor_x`/`floor_y` = metres (homography output);
`position_x`/`position_y` = floor-plan pixels (camera placement); `width_px`/`height_px`
= pixels; `px_per_meter`/`scale` = conversion; bbox `xyxy` = image pixels. Spread across
EEP models, IEP2 projector, IEP3 spatial_voter, IEP5 heatmap/context (30+ files).
**Finding:** no convention marks which fields are px vs m; conversion sites (× scale,
homography apply) are the unit-crossing points and are not annotated.
**Canonical truth:** adopt a naming/annotation convention — metre-valued fields end `_m`
(or are documented), pixel-valued fields end `_px`. `floor_*` (metres) and `position_*`
(pixels) are the main offenders lacking suffixes. **Severity:** medium (a px/m mixup at a
conversion site corrupts positions). **Fix:** document a units convention + a units
registry in `docs/SERVICE_CONTRACTS.md`; annotate each conversion site `# px -> m`; rename
non-conforming fields in a future dedicated migration (DB column renames are heavy — do
deliberately, not opportunistically). **Guardrail:** G4 (unit-suffix lint) — deferred;
needs the registry first to avoid false positives.

## CONS-005 — Per-service metrics ports  ·  Class A  ·  CLOSED (consistent)

**Sites:** IEP1 `9200`, IEP2 `9201`, IEP4 `8004`, YOLO `9400`, REID `9401`.
**Finding:** intentionally DISTINCT per service; `IEP2_METRICS_PORT=9201` agrees across
iep2 main, iep2 metrics, and the Edge Agent that forwards it. No drift. No action.

---

## Guardrails implemented (CI)

`tests/unit/consistency/test_consistency.py` (runs as its own pytest invocation in CI —
reads files only, imports no service code, so it is immune to the cross-service `app`
package collision):
- **G1** embedding dim/byte parity (CONS-001).
- **G5** no `section_id`/`section_ids` in models/routers (CONS-003).

Deferred guardrails: G2 env/Settings parity, G3 schema↔ORM autogenerate-empty, G4 unit-suffix
lint (needs the CONS-004 units registry first).
