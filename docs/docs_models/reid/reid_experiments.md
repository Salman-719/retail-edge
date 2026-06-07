# ReID Module — Experiments & Analysis

This document tracks the evolution of the ReID module, recording observed problems, experiments, and the reasoning behind each change.

**Detection is fixed for all ReID experiments:** `rtdetr-x`, `conf=0.3`, `imgsz=640`.  
**Tracking is fixed:** BoT-SORT with default parameters.  
**ReID is kept outside the tracker** — the `LocalIdentityManager` handles all long-term identity recovery.

---

## Baseline: OSNet x1.0 (ImageNet pretrained)

**Configuration:**
- Model: `osnet_x1_0` via boxmot
- Weights: ImageNet pretrained (NOT person ReID trained)
- Embedding dimension: 512
- Similarity metric: cosine similarity
- ReID threshold: 0.75
- Sampling interval: every 15 frames
- Quality filter: YOLO conf ≥ 0.6 AND bbox area ≥ 2500 px²
- Init embeddings before ReID attempt: 5
- Lost pool TTL: 150 frames (30s at 5 FPS)

**Critical note on baseline weights:** The current model uses ImageNet pretrained weights — a general image classification backbone. It has never been trained to distinguish between different people. It produces 512-dim embeddings but they are not optimised for person re-identification. This is the single most important thing to fix.

### Known weaknesses to investigate

**Problem R1 — Wrong pretrained weights**
ImageNet pretraining teaches the model to classify objects (cats, cars, chairs). Person ReID requires the model to learn fine-grained appearance differences between people wearing similar clothes in similar environments. The two tasks are fundamentally different. A ReID-specific model trained on pedestrian datasets will produce significantly more discriminative embeddings.

**Problem R2 — Threshold not validated**
The 0.75 cosine similarity threshold was set without empirical validation. Too high → fails to recover people who reappear (increases ID switches). Too low → merges different people into the same identity (creates false recoveries). The optimal threshold depends on the embedding model and the specific environment.

**Problem R3 — Sampling interval not validated**
Every 15 frames at 5 FPS = one sample every 3 seconds. This means 5 init embeddings take 15 seconds to collect before a ReID attempt can happen. If the sampling interval is too long, the identity manager is slow to build a gallery. If too short, low-quality embeddings (motion blur, partial occlusion) pollute the gallery.

**Problem R4 — TTL not validated**
150 frames = 30 seconds. If a person leaves for longer than 30 seconds and returns, their identity is lost and they get a new local_id. Whether 30 seconds is the right window depends on the store layout and typical customer behaviour.

---

## What to observe when comparing ReID configurations

| Metric | What it measures | What to watch |
|---|---|---|
| **ID switches** | Times a local_id changes for the same physical person | Primary ReID quality metric — lower is better |
| **Unique people** | Total distinct local_ids issued | Should match true person count — inflation means false new identities, deflation means wrong merges |
| **ReID match rate** | Proportion of ReID lookups that successfully recover a prior identity | Higher = model is discriminative enough to recognise people |
| **ReID false merge rate** | Proportion of ReID recoveries that wrongly merge two different people | Lower = threshold is not too permissive |

**Visual indicators:**
- Does the same person keep the same `L:` label after disappearing and reappearing?
- Does a person who just entered get a label that belonged to someone who left earlier (false merge)?
- How quickly does a new person get a confirmed `L:` label after entering (init speed)?

---

## Candidate ReID models

| Model | Architecture | Training data | Embedding dim | Notes |
|---|---|---|---|---|
| `osnet_x1_0.pt` | OSNet | ImageNet (baseline) | 512 | Not ReID-trained — worst expected |
| `osnet_x1_0_msmt17.pt` | OSNet | MSMT17 (15 cameras, diverse indoor) | 512 | Best generalisation — current best |
| `osnet_x1_0_market1501.pt` | OSNet | Market-1501 (shopping mall) | 512 | Closest environment to retail |
| `osnet_x0_75_msmt17.pt` | OSNet (smaller) | MSMT17 | 512 | Faster, slightly lower accuracy |
| `resnet50_msmt17.pt` | ResNet-50 | MSMT17 | 2048 | Heavier backbone, ~25M params |
| `resnet50_market1501.pt` | ResNet-50 | Market-1501 | 2048 | ResNet + retail environment |
| `mlfn_msmt17.pt` | MLFN | MSMT17 | 512 | Multi-level features, lightweight |
| `agw_msmt17.pt` | AGW | MSMT17 | 512 | Attention + generalized mean pooling — designed for occlusion/pose |
| `clip_market1501.pt` | CLIP | Market-1501 | 1280 | Vision-language, 507MB, slowest |

---

## Round 1 — OSNet vs ResNet: Model Architecture Comparison

**Fixed configuration:** `rtdetr-x`, `conf=0.3`, BoT-SORT default params, `reid_threshold=0.75`

**Models compared:** `osnet_x1_0_msmt17.pt` vs `resnet50_msmt17.pt` (same training data, different architecture)

### Finding

Neither model was strictly better — each made mistakes the other did not:

- **OSNet recovered correctly** in cases where ResNet merged two different people (ResNet threshold too permissive for its embedding space).
- **ResNet recovered correctly** in cases where OSNet failed to re-identify a returning person (OSNet threshold too conservative for that appearance).

### Interpretation

Both models are sensitive to the 0.75 threshold but in different directions. OSNet's 512-dim embeddings and ResNet's 2048-dim embeddings occupy different similarity score distributions — a single threshold cannot be optimal for both simultaneously. OSNet is the better architecture for this task (purpose-built for ReID vs general backbone), but the threshold needs to be validated empirically for each model.

**Conclusion:** OSNet wins on architecture fit, but threshold tuning is required before a fair final comparison can be made.

---

## Round 2 — Threshold Tuning

**Goal:** Find the optimal `reid_threshold` for each model. Both models were misclassifying people at 0.75 — raising the threshold should reduce false merges (different people assigned the same L:) at the cost of potentially missing true recoveries (same person gets a new L: after reappearance).

**Models under test:** All candidate models at multiple threshold values.

**Thresholds to sweep:** 0.75, 0.80, 0.85, 0.90

**What to observe per threshold:**
- Unique people count (inflation = false new IDs, deflation = wrong merges)
- ID switches in the stats bar
- Visual: does the same person keep their `L:` label after reappearing?

<!-- Round 2 results go here -->

---

<!-- Further experiment rounds go here -->
