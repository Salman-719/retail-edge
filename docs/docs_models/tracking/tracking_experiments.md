# Tracking Module — Experiments & Analysis

This document tracks the evolution of the tracking module, recording observed problems, experiments, and the reasoning behind each change.

**Detection is fixed for all tracking experiments:** `rtdetr-x`, `conf=0.3`, `imgsz=640`.  
**ReID is kept outside the tracker** in all experiments — the `LocalIdentityManager` (OSNet x1.0, TTL=150 frames, threshold=0.75) handles long-term identity recovery independently.

---

## Baseline: BoT-SORT (current implementation)

**Configuration:**
- Tracker: BoT-SORT via boxmot
- `with_reid`: False (ReID disabled inside tracker)
- `track_buffer`: 15 frames (~3s at 5 FPS)
- `match_thresh`: 0.8
- `new_track_thresh`: 0.7
- `track_high_thresh`: 0.6
- `track_low_thresh`: 0.1
- `cmc_method`: sof (sparse optical flow — lightweight, cameras are fixed so GMC not needed)
- `frame_rate`: 5

**Why BoT-SORT was chosen over ByteTrack:**
BoT-SORT improves on ByteTrack with a better Kalman filter and more careful association cost matrix. ByteTrack is its direct predecessor and is strictly outperformed. Both are motion-only in our configuration.

### Known weaknesses to investigate

**Problem T1 — Short occlusion drift**
During brief occlusions (person behind shelf for <3s / <15 frames), the Kalman filter prediction drifts because it extrapolates from the last known velocity. When the person reappears, the predicted position may be far enough from the actual position that the IoU match fails, causing the track to be dropped to the lost pool and triggering an unnecessary ReID lookup.

**Problem T2 — New track threshold interaction with RT-DETR**
RT-DETR has bimodal confidence (clusters at <0.20 and >0.70). Our `track_high_thresh=0.6` and `new_track_thresh=0.7` were set when we were using YOLOv8. With RT-DETR, almost all real detections are >0.70, so these thresholds may need revisiting.

**Problem T3 — track_buffer too short**
At 5 FPS, 15 frames = 3 seconds. If a person is occluded for more than 3 seconds (e.g. browsing behind a tall shelf), their track is dropped and ReID must recover them. Extending the buffer delays the ReID lookup but keeps the track alive longer — reducing unnecessary identity churn.

---

## What to observe when comparing trackers

The key metrics for tracking quality (distinct from detection quality):

| Metric | What it measures | What to watch |
|---|---|---|
| **ID switches** | Times a person's local_id changes mid-track | Primary tracker quality metric — lower is better |
| **Unique people** | Total distinct identities over the run | Should stay consistent across trackers — a tracker inflating this is creating ghost tracks |
| **Peak count** | Max simultaneous confirmed tracks | Should match the true number of people in frame |
| **Drop-to-zero** | Frames where confirmed count drops to 0 | Tracker losing all tracks mid-scene — bad |
| **Pending tracks** | Tracks waiting for ReID resolution | High number = tracker creating too many new tracks unnecessarily |
| **ReID match rate** | Proportion of ReID lookups that successfully recover an identity | Tracks the quality of the tracker→ReID handoff |

**What you can observe visually in the UI:**
- **Box stability** — do boxes jump around frame to frame, or do they stay smoothly on the person?
- **ID persistence** — does the same L: label stay on the same person through the whole clip?
- **Ghost boxes** — does the tracker briefly show a box on empty space after a person leaves?
- **Merge/split** — does a single box sometimes split into two, or two boxes merge into one?
- **Border behaviour** — does the tracker hold onto a person entering/exiting the frame border, or does it immediately drop and re-create?

---

## Can we run 4 trackers side by side?

Yes — but it requires a code change. The current experiment UI runs 4 slots with different **models**. To compare trackers we need to fix the model (`rtdetr-x`) and vary the **tracker** per slot instead. This means:

1. Adding a tracker selector dropdown to each slot (BoT-SORT / OCSORT / StrongSORT / ByteTrack)
2. Making the tracker instantiation in `runtime.py` configurable per slot
3. The existing stats (ID switches, unique people, peak count) are already the right metrics — no UI stats changes needed

The tracker parameter changes are in `tracker/tracker.py` — currently hardcoded to BoT-SORT. Making it runtime-selectable is a small refactor.

---

## Candidate trackers for experiments

| Tracker | Key characteristic | Why test it |
|---|---|---|
| BoT-SORT (baseline) | Kalman + IoU, fixed cameras | Current implementation |
| OCSORT | Observation-centric drift correction | Better predicted position after occlusion → tighter spatial gate for ReID |
| StrongSORT | NSA Kalman (confidence-adaptive noise) | RT-DETR's bimodal confidence may benefit from confidence-weighted Kalman updates. Uses our existing OSNet model internally for association — does not add extra ReID compute since the model is already loaded. |
| ByteTrack | Simpler, faster | Sanity check — does BoT-SORT's complexity actually help? |

---

## Round 1 — Tracker Comparison (Motion-Only)

**Objective:** Compare all four trackers head-to-head on the same video with the same detection model, using our established metrics.

**Detection:** `rtdetr-x`, `conf=0.3`, `imgsz=640` (fixed across all slots)  
**Video:** Cam1.mp4

| Metric | BoT-SORT | ByteTrack | OC-SORT | StrongSORT |
|---|---|---|---|---|
| Unique people (track IDs) | **29** | 34 | 51 | 54 |

### Results

The unique track ID count is the most direct measure of tracker quality in this context — it counts how many times the tracker lost and re-created an identity. A lower number means the tracker maintained identity continuity better.

- **BoT-SORT: 29** — best result, fewest unnecessary identity splits
- **ByteTrack: 34** — acceptable, ~17% more identity churn than BoT-SORT
- **OC-SORT: 51** — poor, nearly 2× worse than BoT-SORT despite its observation-centric correction being theoretically suited to occlusion scenarios
- **StrongSORT: 54** — worst result despite having access to ReID embeddings internally

### Why OC-SORT and StrongSORT performed poorly

**OC-SORT:** The observation-centric correction improves predicted position during occlusion, but it has a higher sensitivity to detection noise. RT-DETR's bimodal confidence distribution (clusters at <0.20 and >0.70) means detections appear and disappear more abruptly than YOLO — OC-SORT's correction mechanism may be amplifying this rather than smoothing it.

**StrongSORT:** Having ReID inside the tracker does not help when the tracker's association parameters are not tuned for the scene. StrongSORT's appearance-based association adds complexity without benefit when the appearance embeddings are not discriminative enough at this video resolution and camera angle. The extra ReID step may actually introduce more confusion than it resolves.

**BoT-SORT's advantage:** Its Kalman filter + IoU association is conservative — it holds onto existing tracks longer before dropping them, reducing the number of track-drops that trigger new identity assignments. This conservative behavior is exactly what you want when the ReID is handled externally.

### Conclusion

**BoT-SORT is confirmed as the best tracker for our pipeline.** It produces the fewest unique track IDs (29), meaning the least identity churn, giving the `LocalIdentityManager` the cleanest possible input.

ByteTrack is eliminated — subsequent testing on multiple videos confirmed BoT-SORT consistently produces fewer track IDs than ByteTrack across all tested scenes, not just Cam1. The gap is consistent and meaningful.

OC-SORT and StrongSORT are eliminated — their theoretical advantages do not materialise in practice with RT-DETR detections on retail CCTV footage.

**BoT-SORT is locked in as the tracking module.**

### CPU performance benchmark

Measured on the experiment machine (not Jetson) with 20 simulated camera instances × 300 frames each (6000 total frames, 7 detections per frame):

| Metric | Value |
|---|---|
| Total time (20 cameras sequential) | 25.1s |
| Per-camera time (300 frames) | 1.25s |
| Per-frame association cost | 4.18ms |
| Throughput | 239 frames/sec |

In production the 20 tracker instances run concurrently (one per camera thread). The tracker is **not a bottleneck** — 4.18ms per frame leaves the vast majority of the 200ms per-frame budget (5 FPS) for detection and ReID.

---

## Round 2 — BoT-SORT Parameter Tuning

**Objective:** Now that BoT-SORT is selected, tune its parameters for our specific conditions: RT-DETR detections (bimodal confidence), 5 FPS, retail CCTV, people disappearing behind shelves.

**Key parameters to tune:**

| Parameter | Current | What it controls |
|---|---|---|
| `track_buffer` | 15 frames (3s) | How long a lost track is kept alive before being dropped to ReID |
| `match_thresh` | 0.8 | IoU threshold for associating a detection to an existing track |
| `new_track_thresh` | 0.7 | Minimum confidence to initialise a new track |
| `track_high_thresh` | 0.6 | High-confidence detection threshold for first-pass association |

---

## Round 2 — BoT-SORT Parameter Tuning

**Objective:** Determine whether tuning BoT-SORT's parameters improves on the baseline 29 unique track IDs.

### Round 2a — match_thresh sweep

All slots: `botsort`, `track_buffer=15`, `new_track_thresh=0.7`, `track_high_thresh=0.6`

| match_thresh | Unique track IDs |
|---|---|
| 0.5 | 29 |
| 0.6 | 29 |
| 0.7 | 29 |
| 0.8 (baseline) | 29 |
| 0.85 | 29 |
| 0.9 | 29 |
| 0.95 | 29 |

**Result:** No change across the entire tested range. `match_thresh` has zero impact on tracking quality for this pipeline.

**Why:** RT-DETR-x produces clean, tight bounding boxes with no NMS duplicates. The IoU overlap between a detection and its Kalman-predicted track position is consistently high — well above even 0.95 — so the threshold never becomes the deciding factor in any association decision.

### Round 2b — track_buffer sweep

**Result:** Abandoned. Longer buffers artificially reduce unique track IDs by keeping predicted tracks alive across most of the video window — the metric becomes meaningless. Proper buffer tuning requires ground truth localization accuracy, which is outside the scope of current experiments.

### Conclusion

**BoT-SORT default parameters are optimal for this pipeline.** The clean detection output from RT-DETR-x means the tracker's association step always has high-quality input — parameter sensitivity is effectively zero. No tuning needed.

**Final BoT-SORT configuration:**

| Parameter | Value |
|---|---|
| `track_buffer` | 15 frames (3s at 5 FPS) |
| `match_thresh` | 0.8 |
| `new_track_thresh` | 0.7 |
| `track_high_thresh` | 0.6 |
| `with_reid` | False |
| `cmc_method` | sof |
| `frame_rate` | 5 |

**Next:** ReID experiments.

---

<!-- Experiment rounds go here -->
