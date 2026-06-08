# MLflow Experiments — Cross-Experiment Analysis

A single place that analyses **all three MLflow experiments** (detection, tracking,
reid) together: what was run, what won, what the numbers mean, and the honest limits.
Per-experiment detail lives in the results docs linked below; this is the synthesis.

> **View live:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres minio mlflow` → http://localhost:5000.
> Three experiments: `detection`, `tracking`, `reid`. Model registry: `retailvision-detector`.

| Experiment | Runs | Winner | Detail |
|---|---|---|---|
| detection | 24 | **rtdetr-x, conf=0.5** | [DETECTION_RESULTS](docs_models/detection/DETECTION_RESULTS.md) |
| tracking | 7 | **BoT-SORT, match_thresh=0.8** | [TRACKING_RESULTS](docs_models/tracking/TRACKING_RESULTS.md) |
| reid | 7 | **resnet50_msmt17** (threshold finding: 0.75) | [REID_RESULTS](docs_models/reid/REID_RESULTS.md) |

---

## 1. The pipeline the experiments validate

The three experiments map onto the production vision pipeline, each **fixing the upstream
winner** so the comparison is controlled:

```
detection (rtdetr-x@0.5) → tracking (BoT-SORT) → reid (resnet50_msmt17)
   vary: model, conf        vary: tracker          vary: reid model, threshold
   fixed: —                 fixed: detector        fixed: detector + tracker
```

This staged design is the backbone of the analysis: because each stage holds the prior
winner constant, **any metric difference within an experiment is attributable to that
stage alone** — not contaminated by upstream changes.

---

## 2. What won, and why

### Detection — rtdetr-x @ conf=0.5
- **Decisive on mannequins:** 0 false positives vs 1,686–4,506 for YOLO/seg models — a
  structural win (transformer global attention rejects static figures).
- **Best on real people:** highest confidence (85.6%), peak detection 13 vs true peak 14.
- conf=0.5 over 0.3: cleaner peak count + higher confidence (0.3 over-detects via
  duplicate boxes). [Promoted + registered as `retailvision-detector` Production.]

### Tracking — BoT-SORT @ match_thresh=0.8
- **Lowest identity churn:** `unique_track_ids` 57 + `track_fragmentation` 3.56 (best),
  matching the project's prior `tracking_experiments.md` ranking.
- StrongSORT eliminated (64 id_switches, ~20× slower). match_thresh sweep flat (0.8≈0.9).
- **Trade-off:** ~5–6× slower than ByteTrack/OC-SORT (optical-flow CMC); fine at ≤5 fps,
  ByteTrack is the speed fallback.

### ReID — resnet50_msmt17 (and the threshold finding)
- **Best recovery + fastest:** count_error 18, match_rate 0.60, 13 ms/crop (the OSNets
  are 26 ms). osnet_market1501 a close 2nd (0.57); osnet_msmt17 worst (0.35).
- **Threshold finding:** the resnet50 sweep is strongly monotonic — **0.75** gives the
  best proxy recovery (count_error 8, match_rate 0.71) vs the 0.85 default (18, 0.60).
  A genuine tuning insight, *caveated as proxy-only* (see §4).

---

## 3. Reading the metrics correctly (cross-experiment)

A recurring lesson across all three experiments: **a metric is only meaningful when the
upstream stage is fixed and the metric measures what its name implies.** Two concrete
cases this analysis surfaced:

- **`unique_track_ids` / cumulative-count metrics** were *nonsense in detection* (they
  mixed detection quality with tracking churn) but *valid in tracking* (detection fixed →
  the number isolates tracker churn). Same field, opposite validity depending on context.
  This is why `count_error` was dropped from the detection gate but `track_fragmentation`
  is a primary tracking metric.
- **Peak-per-frame vs cumulative:** detection counting uses `peak_detections_per_frame`
  (a per-frame detection signal, RT-DETR ≈ truth) NOT cumulative track IDs (inflated by
  churn). The distinction is what reconciled "RT-DETR over-counts" (false) with "RT-DETR
  detects well" (true).

**Take-away for anyone reading the dashboards:** check (a) what's held fixed, and (b)
whether the metric is per-frame vs cumulative vs derived, before comparing across runs.

---

## 4. Honest limitations (what the numbers do NOT prove)

| Limitation | Affects | Consequence |
|---|---|---|
| **No ground-truth bounding boxes** | detection | counts are proxies (peak vs labelled peak), not mAP. RT-DETR's "0 mannequin FP" is exact, but crowd counts over-read (NMS-free duplicate boxes). |
| **No per-person identity labels** | reid (mostly), tracking | reid `match_rate`/`count_error` measure *behavior*, not *correctness* — a lower threshold recovers more but could include false merges. The "0.75 > 0.85" finding is **proxy-better**, to validate before production. |
| **Bigger/longer clip than prior docs** | tracking, reid | absolute numbers exceed `*_experiments.md` (1810 vs 302 frames). The **rankings** are the valid output, not absolutes. |
| **Simplified reid recovery** | reid | a re-implementation of `LocalIdentityManager`; faithful for comparison, not identical to production. |
| **Detection over-count propagates** | tracking, reid | duplicate detection boxes → extra tracks → extra identities downstream. True per-person counting is IEP3's job (ReID de-dup), not these stages. |

The artifacts partially compensate for the label gap: the **reid recovery montage**
(gallery-crop vs recovered-crop) is the only way to visually spot-check whether recoveries
are the same person without labels.

---

## 5. The MLflow setup itself (what's demonstrated)

- **Experiment tracking:** 38 runs across 3 experiments, each with params, metrics, tags
  (`phase` / `scene` / `metric_type`), and reproducibility context (seed, git_commit,
  pinned `requirements.txt`) auto-logged on every run.
- **System metrics:** CPU / memory / GPU (utilization, memory, power on the RTX 3070)
  sampled per run.
- **Artifacts:** per-experiment visuals — detection (confidence histogram, annotated +
  peak frames), tracking (track-timeline Gantt), reid (similarity histogram, recovery
  montage), plus `results.json` everywhere.
- **Model registry:** one registered model per experiment — `retailvision-detector`,
  `retailvision-tracker`, `retailvision-reid` — each with a v1 in **Production** (human
  set) and Staging candidates auto-registered by the gate.
- **Promotion gate:** `scripts/check_promotion.py` — **experiment-aware**, scene-aware
  thresholds calibrated from real run data (detection / tracking / reid each have their
  own threshold set); automated *check* + opt-in auto-register to Staging,
  human-in-the-loop Production/deploy. See [MLOPS_PIPELINE](MLOPS_PIPELINE.md).

---

## 6. Next steps / future work
- **Label a clip with per-person identities** → upgrade reid from proxy to true
  match/false-merge accuracy; validate the 0.75 threshold finding before changing prod.
- **Detection box de-duplication** (or rely on IEP3 ReID de-dup) for honest crowd counts.
- **Tracking screenshots / reid screenshots** completion for the report.
- If edge throughput becomes the constraint: revisit ByteTrack (tracking) for speed.
