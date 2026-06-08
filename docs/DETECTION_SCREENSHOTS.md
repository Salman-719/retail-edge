# Detection Experiment — MLflow Screenshots

Visual evidence of the detection experiment in MLflow (24 runs, GPU). These are
static captures; the live setup is reproducible — see
[`MLFLOW_GUIDE.md`](MLFLOW_GUIDE.md) ("run it locally") and the full numeric analysis
in [`docs_models/detection/DETECTION_RESULTS.md`](docs_models/detection/DETECTION_RESULTS.md).

> To regenerate live: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres minio mlflow` → open http://localhost:5000 → experiment **detection**.

---

## 1. Runs table — all 24 detection runs

![Runs table](screenshots/detection/01_runs_table.png)

The `detection` experiment with all 24 logged runs (4 models × 3 scenes + rtdetr-x
conf sweep + yolo11n). Each row is one `(model × conf × scene)` run, tagged
`comparison`/`tuning` and `scene`.

## 2. Model comparison (Compare view)

![Compare models](screenshots/detection/02_compare_models.png)

Side-by-side comparison of the candidate detectors on the crowded scene
(yolov8n / yolov8x / yolo11x-seg / rtdetr-x), generated from logged metrics. This is
the comparison that drove the model decision.

## 3. Winning run — metrics

![Winner metrics](screenshots/detection/03_winner_metrics.png)

`rtdetr-x_conf0.5_crowded` — the promoted detector. Key metrics: `avg_confidence`
85.6%, `peak_count_error` 1 (peak 13 vs true 14), `id_switches` 7.

## 4. Mannequin rejection — the decisive result

![Mannequin rejection](screenshots/detection/04_mannequin_rejection.png)

On the mannequin clip (0 real people, 8 mannequins) RT-DETR scores
`false_positive_total = 0` — perfect 3-D mannequin rejection — versus thousands of
false positives for the CNN/segmentation models. The strongest single finding.

## 5. Run artifacts — peak-detection frame

![Artifacts / peak frame](screenshots/detection/05_artifacts_peakframe.png)

Per-run artifacts (confidence histogram, annotated sample frames, the busiest
"peak" frame, `results.json`, `requirements.txt`). The peak frame shows the
detector's busiest moment for visual inspection.

## 6. Model Registry — promoted model

![Model registry](screenshots/detection/06_registry.png)

`retailvision-detector` in the MLflow Model Registry: v1 = Production (manually
promoted, human-in-the-loop), v2 = Staging (auto-registered candidate via the
promotion gate). See [`MLOPS_PIPELINE.md`](MLOPS_PIPELINE.md) §3.

---

**Promotion gate** (`scripts/check_promotion.py`) verdict on the promoted run
(`rtdetr-x_conf0.5_crowded`): **PROMOTE** — `avg_confidence` ≥ 75 ✅,
`id_switches` ≤ 12 ✅, `peak_count_error` ≤ 2 ✅.
