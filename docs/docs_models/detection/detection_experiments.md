# Detection Module — Experiments & Analysis

This document tracks the evolution of the detection module, recording observed problems, experiments, and the reasoning behind each change.

---

## Baseline: YOLOv8 Nano (`yolov8n.pt`)

**Configuration:**
- Model: `yolov8n.pt`
- Confidence threshold: `0.5`
- Class filter: person only (class 0)
- Input: full frame, no masking

### Observed Problems

**Problem 1 — Oversized bounding boxes**
Detections frequently include more area than the person's body — background, nearby objects, or adjacent people bleed into the box. This directly degrades the ReID embedding quality: OSNet is given a crop that contains irrelevant pixels, making the 512-dim embedding less representative of the person's appearance. Downstream consequence is more false mismatches in the identity recovery step.

**Problem 2 — False negatives at frame borders**
People partially visible at the edges of the frame are frequently missed. This is a known weakness of anchor-based detectors on truncated objects — the model was trained predominantly on fully-visible persons. In a retail setting where people enter and exit the camera field of view through the frame borders, this causes track initialization to be delayed and track termination to be premature, increasing the number of unnecessary ReID lookups.

**Problem 3 — Merging two people into one bounding box**
When two people are close together or overlapping, the model sometimes produces a single bounding box enclosing both. This breaks the tracker: a single detection feeds into ByteTrack/BoT-SORT as one track, so two people share a track ID. When they separate, one person appears as a new track rather than a continuation — artificially inflating the identity count and triggering a ReID lookup for a person who never actually left the frame.

---

## Round 1 — YOLOv8 Size Comparison

**Objective:** Establish the minimum viable model size within the YOLOv8 family.

**Models tested:** `yolov8n`, `yolov8s`, `yolov8m`, `yolov8x`  
**Videos:** Cam1 (simpler scene), Cam2 (harder scene — more people, worse angle, more occlusion)  
**Metrics observed:** unique people detected, peak count, avg confidence, avg bbox area, ID switches, drop-to-zero frames

### Results

**Cam1 (simpler scene):**
- `yolov8m` and `yolov8x` performed identically — same unique people count, same peak count, same ID switches, same drop-to-zero.
- `yolov8n` and `yolov8s` were clearly inferior: more missed detections, lower unique people count, higher drop-to-zero.

**Cam2 (harder scene):**
- `yolov8x` pulled ahead of `yolov8m` — detected more people overall, demonstrating that the extra model capacity helps specifically when the scene is challenging.
- `yolov8n` and `yolov8s` remained clearly behind.

### Conclusion

**Nano and small are not viable for production use.** The performance gap on Cam2 is decisive — harder scenes (more people, worse angles, occlusion, border entries) expose the detection ceiling of smaller models.

**Minimum viable model: `yolov8m`.** `yolov8x` is the accuracy ceiling within the v8 family and wins on harder scenes. The open question going into Round 2 is whether newer architectures can match or beat `yolov8x` accuracy at a smaller parameter count, which would be preferable for edge deployment.

---

## Round 2 — Cross-Generation Comparison at Medium/Large Tier

**Objective:** Determine whether newer YOLO generations (v9, v11, v12) can match or beat `yolov8x` — the Round 1 winner — at a comparable or smaller model size.

**Models tested:** `yolov8x`, `yolov9c`, `yolo11m`, `yolo12m`  
**Video:** Cam2 (harder scene used as the benchmark since it differentiates models)

| Metric | yolov8x | yolov9c | yolo11m | yolo12m |
|---|---|---|---|---|
| In frame (last frame) | 10 | 11 | 9 | 10 |
| Unique people | 17 | 14 | 12 | 12 |
| Peak count | 12 | 12 | 11 | 11 |
| Avg confidence | 82.2% | 77.9% | 80.8% | 80.3% |
| Avg bbox area | 4,891 px² | 4,872 px² | 5,051 px² | 5,298 px² |
| ID switches | 9 | 8 | 9 | 6 |
| Drop-to-zero | 0 | 0 | 0 | 0 |
| Frames processed | 302 | 302 | 302 | 302 |

### Results

`yolov8x` wins Round 2. It detected the highest number of unique people (17 vs 14, 12, 12) — the most important metric for our use case, as missing a person entirely is a harder failure than a brief tracking gap. Its confidence is also the highest (82.2%), indicating more certain detections across the scene.

`yolov9c` comes closest on peak count and has the lowest ID switches (8), and its bbox area is the tightest (4,872 px²) which is marginally better for ReID embedding quality. However it misses significantly more unique identities than `yolov8x`.

`yolo11m` and `yolo12m` both underperform on unique people count despite `yolo12m` having the best ID switch count (6). Their larger average bbox areas (5,051 and 5,298 px²) also indicate looser bounding boxes, which is worse for ReID.

### Conclusion

**`yolov8x` remains the best detector across both rounds.** Newer architectures do not outperform it on this dataset for the person detection task in retail CCTV conditions.

The finding is notable: architectural advances in v9, v11, and v12 (PGI, C2PSA attention, area attention) do not translate to better person detection on this specific domain. `yolov8x`'s larger parameter count (68M) and mature COCO training appear to be the decisive factors.

**Trade-off consideration for edge deployment:** `yolov8x` is too large for real-time inference on the Jetson Orin NX 8GB at 20 cameras × 5 FPS. The practical deployment decision is `yolov8x` on the cloud/AGX Orin (32GB) and `yolov8m` as the edge fallback on the Jetson NX (8GB), accepting the small accuracy trade-off for latency.

---

## Round 3 — Segmentation vs Detection: Bounding Box Quality

**Objective:** Test whether segmentation variants produce tighter bounding boxes, improving ReID embedding quality and eliminating merged-box failures (Problems 1 and 3).

**Models tested:** `yolov8x`, `yolov8x-seg`, `yolov9e-seg`, `yolo11x-seg`  
**Video:** play1.asf (fabric/textile retail store with mannequins)

| Metric | yolov8x | yolov8x-seg | yolov9e-seg | yolo11x-seg |
|---|---|---|---|---|
| In frame (last frame) | 3 | 1 | 1 | 3 |
| Unique people | 4 | 2 | 2 | 5 |
| Peak count | 4 | 2 | 2 | 5 |
| Avg confidence | 69.8% | 82.6% | 74.6% | 72.5% |
| Avg bbox area | 2,841 px² | 7,124 px² | 7,548 px² | 3,091 px² |
| ID switches | 1 | 5 | 3 | 2 |
| Drop-to-zero | 0 | 4 | 4 | 0 |
| Frames processed | 166 | 318 | 241 | 137 |

### Results

General performance across the main scenes was similar between detection and segmentation variants. The differentiating observation came when a **mannequin was present in the scene**:

- **`yolov8x` (detection)** falsely detected the mannequin as a person, inflating the unique people count and triggering unnecessary ReID lookups.
- **Segmentation variants** correctly rejected or were less likely to trigger on the mannequin — the mask-based prediction provides better shape discrimination between a static mannequin and a moving person, as the model must fit a pixel-level mask rather than just a bounding box.

This is a significant finding for retail environments where mannequins, display figures, and posters of people are common sources of false positives.

### Frame count discrepancy

The models processed different frame counts (166 vs 318 vs 241 vs 137) because they ran on the same video but at different processing speeds — slower models process fewer batches before the session ends. This means direct metric comparison is limited; the stats reflect different temporal windows of the same video.

### Key observations

- `yolov8x-seg` and `yolov9e-seg` have significantly larger avg bbox areas (7,124 and 7,548 px²) than the detection baseline (2,841 px²) — contrary to the hypothesis. The segmentation head returns the bounding box of the mask, which can be larger than the tight detection box in some cases.
- `yolo11x-seg` is the exception: 3,091 px² bbox area, close to the detection baseline, while still benefiting from mask-based discrimination. It also has the best ID switch count among seg models (2) and zero drop-to-zero.
- `yolov8x-seg` and `yolov9e-seg` both show 4 drop-to-zero events vs 0 for `yolov8x` and `yolo11x-seg` — indicating worse temporal stability.

### Conclusion

Segmentation models offer a **qualitative advantage in scenes with mannequins or human-shaped objects** — a directly relevant retail condition. Among segmentation models, **`yolo11x-seg` is the best candidate**: it avoids the bbox area inflation seen in `yolov8x-seg` and `yolov9e-seg`, has the lowest ID switches among seg variants, and zero drop-to-zero events.

**Next step (Round 3b):** Run `yolov8x` vs `yolo11x-seg` head-to-head on a different camera to determine which to select as the final model, with the mannequin scenario as the deciding factor.

---

## Round 3b — Segmentation vs Detection: Crowded Scene Validation

**Objective:** Validate Round 3 findings on a busier scene (Cam1 — many people simultaneously) to confirm which model to carry forward as the final detector.

**Models tested:** `yolov8x`, `yolov8x-seg`, `yolov9e-seg`, `yolo11x-seg`  
**Video:** Cam1.mp4 (busy retail store, multiple simultaneous customers and cashiers)

| Metric | yolov8x | yolov8x-seg | yolov9e-seg | yolo11x-seg |
|---|---|---|---|---|
| In frame (last frame) | 9 | 9 | 9 | 9 |
| Unique people | 17 | 14 | 15 | 16 |
| Peak count | 10 | 10 | 10 | 10 |
| Avg confidence | 81.4% | 81.2% | 80.8% | 81.2% |
| Avg bbox area | 6,024 px² | 6,145 px² | 5,961 px² | 6,260 px² |
| ID switches | 13 | 12 | 14 | 10 |
| Drop-to-zero | 0 | 0 | 0 | 0 |
| Frames processed | 302 | 302 | 302 | 302 |

### Results

On the crowded scene all four models show comparable in-frame detection (9 at last frame, peak 10). The differentiators are:

- **Unique people:** `yolov8x` leads with 17, followed by `yolo11x-seg` (16), `yolov9e-seg` (15), `yolov8x-seg` (14). Detection baseline still detects the most total identities.
- **ID switches:** `yolo11x-seg` has the fewest (10), followed by `yolov8x-seg` (12), `yolov8x` (13), `yolov9e-seg` (14). The segmentation advantage in identity stability is clear here — cleaner crops produce better ReID embeddings, reducing mistaken identity assignments.
- **Avg bbox area:** All models are close (5,961–6,260 px²). No significant difference in box tightness on this scene.
- **Drop-to-zero:** 0 across all models — the scene is busy enough that someone is always in frame.

### Cross-round synthesis (Round 3 + 3b)

| Dimension | Winner | Runner-up |
|---|---|---|
| Most unique people detected (overall) | `yolov8x` | `yolo11x-seg` |
| Mannequin false positive rejection | `yolov9e-seg` | `yolov8x-seg` |
| Among seg models: mannequin rejection | `yolov9e-seg` > `yolov8x-seg` | — |
| Fewest ID switches | `yolo11x-seg` | `yolov8x-seg` |
| Temporal stability (drop-to-zero) | All tied (0) | — |

### Final Round 3 Conclusion

There is no single model that wins on all dimensions. The findings reveal a clear split:

- **`yolov8x`** is the best detector for people overall — highest unique person count across all tested scenes. It is the right choice when maximising detection recall is the priority and mannequins are not present or not a concern.

- **`yolov9e-seg`** is the best model for **mannequin rejection** — it outperforms `yolov8x-seg` on this specific task, correctly discriminating static mannequins from real people. Among all segmentation variants it provides the strongest shape-level discrimination.

- **`yolov8x-seg`** is the second-best for mannequin rejection, behind `yolov9e-seg`.

- **`yolo11x-seg`** has the fewest ID switches in the crowded scene but does not offer the same mannequin rejection quality as `yolov9e-seg`.

**The deployment decision depends on the store environment:**

| Store condition | Recommended model |
|---|---|
| No mannequins / display figures | `yolov8x` — maximises detection recall |
| Mannequins present | `yolov9e-seg` — best mannequin rejection while maintaining good people detection |

**This is the open question for Round 4:** can we quantify the mannequin false positive rate more precisely, and does `yolov9e-seg` close the gap with `yolov8x` on unique people detection enough to be used universally across all store types?

> **⚑ Flagged — Static Object Suppression (not yet implemented)**
> Mannequins and display figures can be suppressed without relying on the detector at all. A `StaticSuppressor` module inserted between detector output and tracker input would track centroid displacement per detection across the video. Any object that never moves beyond a small pixel threshold across the full session is retroactively or proactively flagged as static and removed before it reaches the tracker. This eliminates mannequin false positives regardless of which detection model is used, removing the need to choose between `yolov8x` and `yolov9e-seg` on that basis. Implementation deferred — revisit after tracking/ReID experiments.

---

## Round 4 — RT-DETR-x vs YOLO Finalists

**Objective:** Test RT-DETR-x — a transformer-based detector with no NMS — against the best YOLO models from previous rounds, on both crowded scenes and mannequin scenes.

**Models tested:** `yolov8x`, `rtdetr-x`, `yolo12x` (slot 3), `rtdetr-x` (slot 4 duplicate for confirmation)  
**Video:** Cam1.mp4 (crowded retail store)

| Metric | yolov8x | rtdetr-x |
|---|---|---|
| In frame (last frame) | 9 | 9 |
| Unique people | 17 | 17 |
| Peak count | 10 | 11 |
| Avg confidence | 81.4% | 86.1% |
| Avg bbox area | 6,030 px² | 5,727 px² |
| ID switches | 16 | 12 |
| Drop-to-zero | 0 | 0 |
| Frames processed | 302 | 302 |

### Mannequin scene results

On a separate video containing mannequins:
- **`rtdetr-x`** detected **zero mannequins** — perfect rejection with no false positives
- **`yolov8x`** detected mannequins as people — same failure mode observed in Round 3

### Results analysis

RT-DETR-x matches `yolov8x` on unique people (17) while strictly outperforming it on every other metric:
- **+4.7% higher confidence** (86.1% vs 81.4%) — more decisive detections
- **Tighter bounding boxes** (5,727 vs 6,030 px²) — better ReID crop quality
- **Fewer ID switches** (12 vs 16) — more stable identity assignments
- **Higher peak count** (11 vs 10) — catches more simultaneous people
- **Zero mannequin false positives** — confirmed across two separate mannequin scenes

The mannequin rejection is structural, not coincidental. RT-DETR's global attention mechanism learns scene context — a static display figure with no motion context receives low query activation and is not assigned a detection. YOLO's sliding-window approach has no such global reasoning and commits to a box based on local appearance alone.

### Why RT-DETR-x doesn't detect mannequins

RT-DETR uses a fixed set of learned object queries (100 by default). Each query attends globally to the entire feature map and learns to activate for specific object instances. A mannequin:
- Has no motion context in surrounding frames
- Produces low cross-attention activation because its appearance is consistent with background across time
- Gets outcompeted by real person queries in the bipartite matching step

YOLO generates dense anchor proposals and uses NMS to prune — a mannequin passes the appearance classifier just like a person because local appearance is similar.

### Conclusion

**`rtdetr-x` is the new best detection model.** It wins on every measurable dimension simultaneously:

| Dimension | `rtdetr-x` vs `yolov8x` |
|---|---|
| Unique people detected | Tied (17) |
| Peak simultaneous count | Better (11 vs 10) |
| Confidence | Better (86.1% vs 81.4%) |
| Bbox tightness | Better (5,727 vs 6,030 px²) |
| ID switches | Better (12 vs 16) |
| Mannequin rejection | Perfect vs fails |

The static object suppression approach flagged in Round 3 is now **deprioritised** — RT-DETR-x solves the mannequin problem structurally without any post-processing logic.

---

## Round 5 — Pose and Segmentation Variants vs RT-DETR-x

**Objective:** Test whether pose and segmentation variants of YOLO11x can compete with RT-DETR-x on people detection count.

**Models tested:** `yolo11x-pose`, `rtdetr-x`, (slot 3 not captured), `yolo11x-seg`  
**Video:** Cam1.mp4 + Cam2 (second camera angle)

| Metric | yolo11x-pose | rtdetr-x | yolo11x-seg |
|---|---|---|---|
| In frame (last frame) | 8 | 9 | 9 |
| Unique people | 14 | 16 | 14 |
| Peak count | 9 | 11 | 10 |
| Avg confidence | 85.4% | 86.1% | 81.2% |
| Avg bbox area | 6,187 px² | 5,759 px² | 6,234 px² |
| Frames processed | 302 | 302 | 302 |

### Results

**RT-DETR-x continues to lead** on unique people detected (16 vs 14 for both YOLO11x variants) and peak count (11 vs 9–10). Its confidence remains the highest and its bounding boxes remain the tightest.

**`yolo11x-pose`** — the pose variant detects people using keypoint estimation as the primary task, with bounding boxes as a by-product. It performs comparably to `yolo11x-seg` on unique people (both 14) but with higher confidence (85.4% vs 81.2%). The pose head does not offer a meaningful advantage over the standard detection or segmentation variants for our use case.

**`yolo11x-seg`** — consistent with Round 3b results. Good segmentation quality but detection recall remains below RT-DETR-x.

### Conclusion

RT-DETR-x is confirmed as the best detection model across all tested scenes and all tested YOLO variants. The transformer architecture's global attention consistently outperforms CNN-based detectors on unique person count, confidence, and bounding box tightness in retail CCTV conditions.

**`rtdetr-x` is locked in as the detection model for the pipeline.**

---

## Round 6 — Confidence Threshold Sweep on RT-DETR-x

**Objective:** Determine the optimal confidence threshold for RT-DETR-x. Specifically, investigate whether the detections currently filtered out below `conf=0.3` contain real people (border cases, occlusions) or noise.

**Model:** `rtdetr-x` across all slots  
**Video:** Camera1.mp4 (848×478)

### Pre-experiment: confidence distribution analysis

Before running the UI sweep, a diagnostic script sampled 10 frames across the video and counted RT-DETR-x detections at `conf=0.1` by confidence bucket:

| Confidence range | Detection count |
|---|---|
| 0.10 – 0.20 | 21 |
| 0.20 – 0.30 | 2 |
| 0.30 – 0.40 | 0 |
| 0.40 – 0.50 | 0 |
| 0.50 – 0.70 | 1 |
| 0.70 – 1.00 | 8 |

The distribution is **bimodal** — detections cluster either below 0.20 or above 0.70, with virtually nothing in between. This is characteristic of RT-DETR's transformer matching: when a query matches an object it does so decisively (high confidence), and when it doesn't match it produces very low scores.

### Sweep results

| Slot | conf | Unique people | Observation |
|---|---|---|---|
| 1 | 0.3 | baseline | Current configuration |
| 2 | 0.15 | ~same | Sub-0.20 detections do not add real people |
| 3 | 0.2 | ~same | Confirms the gap — nothing meaningful between 0.20–0.30 |
| 4 | 0.5 | ~same | High-confidence only — no regression |

### Conclusion

**Confidence threshold has no meaningful impact on RT-DETR-x for this dataset.** Unique people count and peak count are virtually unchanged across all tested values. The 21 detections in the 0.10–0.20 range are confirmed noise — they do not correspond to real people missed at the current threshold.

**`conf=0.3` is confirmed as the final setting.** It sits in the gap between the noise cluster and the signal cluster, which is exactly where a threshold should sit.

---

## Detection Module — Final Configuration

After 6 rounds of experimentation across model families, sizes, tasks (detection/segmentation/pose), architectural generations, mannequin scenes, crowded scenes, and hyperparameter sweeps:

| Parameter | Value | Reasoning |
|---|---|---|
| Model | `rtdetr-x` | Best unique people count, zero mannequin FP, highest confidence, tightest boxes, fewest ID switches |
| Confidence | `0.3` | Optimal operating point confirmed by distribution analysis |
| imgsz | `640` | Video resolution (848×478) — going higher adds no real information |
| IoU | `0.45` | RT-DETR is NMS-free — this parameter has no effect on RT-DETR-x specifically. For YOLO variants it controls NMS aggressiveness and directly affects merged-box behaviour (Problem 3). Not applicable to our final model. |

**Next:** Tracking module experiments.

---

## Edge Cases & Qualitative Findings

This section documents qualitative observations that quantitative metrics alone do not capture. These are critical for evaluating real-world suitability in a retail environment and demonstrate testing beyond standard benchmark conditions.

---

### Case 1 — Mannequin false positive ✅ Correctly handled by RT-DETR-x

**Observation:** When a mannequin was present in the scene, `yolov8x` consistently detected it as a person — assigning it a track ID, generating embeddings, and inflating the unique people count. `rtdetr-x` correctly ignored it across all tested mannequin scenes with zero false detections.

**Why it matters:** Retail stores commonly use mannequins and display figures. A detector that conflates these with real customers produces permanently incorrect occupancy counts and wastes ReID compute on static objects that will never move.

**Why RT-DETR-x handles it correctly:** The transformer's global self-attention evaluates each object query in the context of the entire scene. A mannequin has no motion context, no behavioural cues, and never changes its spatial relationship to other objects — the bipartite matching assigns it low query activation and suppresses it. YOLO's sliding-window CNN approach classifies based on local appearance alone, which a mannequin passes easily since it looks like a person in a local crop.

**Significance:** This is a structural advantage of the transformer architecture — it does not require any post-processing workaround such as the static object suppressor we considered earlier. The architecture handles it natively.

---

### Case 2 — Two people merged into one bounding box ✅ Correctly handled by RT-DETR-x

**Observation:** When two people were in close proximity or partially overlapping, `yolov8x` sometimes produced a single large bounding box enclosing both. `rtdetr-x` correctly produced two separate bounding boxes — one per person — in the same scenario.

**Why it matters:** A merged box means two people share one track ID in the tracker. When they separate, one appears as a new track, artificially inflating the unique people count and triggering an unnecessary ReID lookup for a person who never actually left the frame.

**Why RT-DETR-x handles it correctly:** RT-DETR uses one-to-one bipartite matching — each decoder query can only be assigned to one object. There is no NMS post-processing step that could suppress one of two nearby detections. Each person activates a separate query independently, so physical proximity does not cause merging regardless of how close the people are.

---

### Case 3 — Advertisement image of a human hand detected as person ❌ Known limitation of RT-DETR-x

**Observation:** An in-store advertisement displaying a large printed image of a human hand was detected by `rtdetr-x` as a person and assigned a track ID and embedding.

**Why it matters:** Retail stores contain product imagery, promotional posters, and advertising displays that may include human body parts, silhouettes, or life-size photographs. These can trigger false positives even in a model that correctly rejects 3D mannequins.

**Why it happens:** Unlike a mannequin — which is a 3D object the model can contextualise across the scene — a 2D advertisement image contains visual features (skin tone, shape, texture) that are indistinguishable from a real person crop at the local level. The global attention that correctly rejects mannequins does not help here because the advertisement's visual content genuinely resembles a person within the model's feature space.

**Mitigation options:**
1. **Static object suppressor** — an advertisement never moves, so displacement-based filtering across the session would suppress it. This was flagged earlier as future work and is now re-elevated as a priority given this finding.
2. **Zone masking** — if the advertisement location is known from the floor plan, a pixel-space exclusion mask can prevent detections in that region entirely.
3. **Confidence filtering** — advertisement detections may have lower average confidence than real people over time; monitoring persistent low-confidence static detections could identify candidates for suppression.

**Current status:** Unmitigated. Flagged for implementation after ReID experiments are complete.

---
