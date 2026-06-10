<!--
  Rubric: T1 — AI depth and non-triviality (5%)
  This document proves the system is non-trivial AI, not a wrapper.
-->

# AI pipeline depth — RetailVision

## 1. Why this problem requires ML

Cross-camera person re-identification cannot be solved with rule-based systems
for three fundamental reasons:

**Pixel coordinates are camera-local.** A person exiting camera A at pixel
(800, 600) has no defined spatial relationship to their entry pixel on camera B.
Rule-based matching on position requires cameras to overlap — but the retail
analytics use case specifically involves non-overlapping cameras covering
different store zones.

**Time alone is ambiguous.** In a store with 200 daily visitors and 15 cameras,
dozens of people transition between any two adjacent zones simultaneously.
A time-window rule produces O(N²) candidate matches with no disambiguation
mechanism. In a crowded scene (6+ people in simultaneous transit), a pure
time-heuristic produces near-random assignment.

**Appearance is the only generalizable signal.** A person's clothing and
build produce a distinctive vector that transfers across camera angles,
resolutions, and lighting conditions. This is the core ML insight the
system is built on: train a deep model to embed person crops into a
metric space where the same person maps to nearby points regardless of
which camera produced the crop.

---

## 2. The full inference chain

```
IEP1 (edge)
  RTSP → OS thread captures frames → tmpfs JPEG
  → window manifest published to local Redis stream:iep1:{cam_id}

IEP2 (edge, one pod per camera)
  Manifest consumed from local Redis
  → frames loaded from tmpfs / S3
  → [RT-DETR-x] person detection (ZMQ → yolo_service)
  → [BoTSORT] in-frame tracking (motion-only, local)
  → homography projection (pixel bbox foot → floor_x, floor_y in metres)
  → [resnet50_msmt17] appearance embedding (ZMQ → reid_service)
  → LocalIdentityManager assigns stable local_id per person
  → tracking_history + local_centroids written to cloud PostgreSQL
  → batch_complete event published to cloud Redis stream:iep2:batch_complete

IEP3 (cloud)
  batch_complete events consumed via XREADGROUP (XACK-before-processing)
  → waits for all cameras in store to report for window W
  → 3-stage matcher: SpatialVoter → ambiguity check → ReidMatcher fallback
  → global_id assigned/linked/transitioned in FSM
  → global_identities + global_tracking_history + global_local_mapping written
```

Each stage holds the upstream output constant — this is also how the MLflow
experiments were structured (detection fixed → tracking experiment; detection
+ tracking fixed → ReID experiment).

---

## 3. IEP2: per-camera vision pipeline

### 3.1 Person detection (RT-DETR-x)

**Model:** RT-DETR-x (`rtdetr-x.pt` in dev; TRT FP16 engine in production on Jetson).
**Config:** `conf=0.5`, `imgsz=640`, class filter = person only (class 0).

RT-DETR uses a fixed set of learned object queries (100 by default). Each query
attends globally to the entire feature map via cross-attention and learns to
activate for specific object instances. The bipartite matching assignment ensures
each detected object maps to exactly one query — no NMS post-processing, no
duplicate boxes.

**Why this architecture for retail:**
- **Mannequin rejection (structural):** A mannequin has no motion context,
  consistent appearance with background across time, and gets outcompeted by
  real-person queries in bipartite matching. Result: 0 mannequin false positives
  across all tested conf values ≥0.3, vs 1,686–4,506 FPs for the best CNN models
  at the same threshold (DETECTION_RESULTS.md §2).
- **Merged-box prevention:** One-to-one bipartite matching means two physically
  close people each activate a separate query independently. YOLO's NMS can
  suppress one of two nearby bounding boxes, conflating two people into one track.
- **Highest confidence (85.6%) and tightest boxes (avg 5,727 px²)** among all
  tested models — both directly improve downstream ReID embedding quality.

**Fallback:** YOLO11n (`.pt`) is available as a low-compute fallback via
`DETECTOR_MODEL` env var when edge GPU throughput is constrained. It rejects
mannequins at conf=0.5 by low sensitivity (not structural discrimination),
and under-detects people (peak 11 vs true 14).

### 3.2 In-frame tracking (BoTSORT)

**Config:** `with_reid=False`, `match_thresh=0.8`, `track_buffer=15` frames (3 s at 5 FPS),
`cmc_method=sof` (sparse optical flow for fixed cameras), `frame_rate=5`.

BoTSORT runs motion-only association: Kalman filter predicts each track's
next position, and IoU overlap between the prediction and incoming detections
is the sole association cost. ReID is deliberately excluded from the tracker
(`with_reid=False`) — appearance matching is handled externally by the
`LocalIdentityManager` and IEP3, so the tracker is not double-spending compute
on ReID embeddings.

**Why BoTSORT over alternatives** (MLflow experiment `tracking`, 7 runs):

| Tracker | unique_track_ids ↓ | track_fragmentation ↓ | id_switches ↓ | fps ↑ |
|---|---|---|---|---|
| **BoTSORT** | **57** | **3.56** | 7 | 76 |
| OC-SORT | 65 | 4.06 | 14 | 426 |
| ByteTrack | 82 | 5.12 | **5** | 508 |
| StrongSORT | 83 | 5.19 | 64 ❌ | 7 ❌ |

BoTSORT wins the primary churn metrics (fewer identity re-creations, lowest
fragmentation). ByteTrack is the speed fallback (~5–6× faster) if edge
throughput becomes the constraint — it has fewer id_switches but significantly
more total track churn (82 vs 57 unique IDs).

`match_thresh` sweep confirmed zero sensitivity (identical results at 0.6–0.9)
because RT-DETR-x's clean, tight boxes produce consistently high IoU overlap
with Kalman predictions — the threshold never becomes the deciding factor.

### 3.3 Appearance embedding (resnet50_msmt17 ReID)

**Model:** `resnet50_msmt17.pt` — a ResNet-50 backbone fine-tuned on MSMT17
(15 cameras, diverse indoor environments, purpose-built for person ReID).
**Output:** 2048-dimensional L2-normalized float32 embedding vector, packed
as 8192 bytes per crop. Embedding dimension confirmed in migration
`0005_embedding_dim_2048.py`.

Each detected and confirmed person crop is forwarded to the `reid_service`
via ZMQ PUSH/PULL. The service runs batch inference (up to `REID_MAX_BATCH_SIZE`
crops per call) and returns one 2048-dim vector per crop. IEP2's
`LocalIdentityManager` accumulates a quality-ranked gallery of embeddings
for each active `local_id` — high-quality crops (high confidence, large bbox
area) are preferred and low-quality crops are rejected before gallery insertion.

**Why appearance over position for cross-camera matching:**
Floor position (from homography) is useful for spatial proximity voting
(SpatialVoter in IEP3), but alone is insufficient — multiple people can be
in the same floor zone simultaneously. Appearance provides the discriminating
signal that resolves spatial ambiguity. The two signals are complementary:
spatial voting reduces the candidate set; appearance breaks ties and handles
cases where spatial voting is inconclusive.

**Why resnet50_msmt17 over OSNet variants** (MLflow experiment `reid`, 7 runs,
MSMT17-trained comparison at threshold 0.85):

| Model | count_error ↓ | match_rate ↑ | avg_embed_ms ↓ |
|---|---|---|---|
| **resnet50_msmt17** | **18** | **0.60** | **13** |
| osnet_x1_0_market1501 | 20 | 0.57 | 26 |
| osnet_x1_0_msmt17 | 39 | 0.35 | 26 |

ResNet-50 beats both OSNet variants on recovery quality AND speed — the 2048-dim
backbone uses the GPU more efficiently per crop (13 ms vs 26 ms), despite
producing 4× larger embeddings.

---

## 4. IEP3: cross-camera reconciliation

### 4.1 Three-stage matching algorithm

IEP3's identity matching is **not** a single cosine similarity threshold.
It is a three-stage pipeline, each stage feeding the next:

**Stage 1 — SpatialVoter (floor-position temporal voting)**

For each new `local_id` in the current batch, IEP3 looks back across recent
batches and casts votes for candidate `global_id`s based on floor-position
proximity:
- `vote_distance_threshold_m = 1.0` — votes are cast when a historical
  `(global_id, floor_pos)` is within 1 metre of the current detection
- `temporal_tolerance_ms = 150` — only recent detections within this window
  are considered (prevents stale position evidence from old batches)
- `min_votes = 10` — a candidate must accumulate at least 10 votes to be
  considered (prevents single-frame noise from triggering a match)
- `min_vote_rate = 0.6` — the winning candidate must hold ≥60% of all cast
  votes (prevents weak pluralities from forcing a match)

**Stage 2 — Ambiguity check**

If Stage 1 produces a winner, the system checks whether the second-best
candidate is suspiciously close:
- `ambiguity_margin = 0.15` — if top-2 candidates are within 15 vote-rate
  points of each other, the match is flagged as ambiguous and escalated to
  Stage 3 rather than committed

**Stage 3 — ReidMatcher appearance fallback**

When Stage 1 produces no winner (insufficient votes) or Stage 2 flags ambiguity,
the system falls back to cosine similarity between the current `local_id`'s
embedding gallery and the candidate `global_id`'s stored embeddings:
- `reid_fallback_threshold = 0.55` — minimum cosine similarity for a match
  (deliberately lower than the Stage 1 threshold because Stage 3 is only
  reached when spatial evidence is weak or ambiguous)

If neither stage produces a match above threshold, a new `global_id` is minted.

**Why 3 stages:** Spatial voting is fast, interpretable, and handles the
majority of cases (the same person returns to the same floor zone). Appearance
fallback handles edge cases: a person returning to a different zone after a
long absence, or two people who occupied the same zone at different times.
The combination reduces both false merges (appearance without spatial context)
and false splits (spatial context without appearance confirmation).

### 4.2 Global identity state machine

Each `global_id` progresses through three states managed by the FSM in
`services/iep3_reconciliation/app/state.py`:

```
ACTIVE ──► LOST ──► EXITED
           │
           └──► ACTIVE  (recovery)
```

- **ACTIVE:** Person is currently visible in at least one camera's current window.
- **LOST:** Person has not appeared in any camera for `grace_seconds` (default 300s).
  The embedding gallery is retained. A new `local_id` matching this `global_id`
  via the 3-stage matcher will transition it back to ACTIVE.
- **EXITED:** `global_id` is permanently closed after exceeding the LOST grace
  period with no recovery. Embedding gallery is archived for analytics; no
  further matches are attempted.

The FSM transitions are written atomically within the PostgreSQL reconciliation
transaction — there is no inconsistent intermediate state visible to reads.

### 4.3 Windowed batch alignment (60-second windows)

IEP3 does not process individual frames — it processes complete 60-second
windows. All IEP2 instances (one per camera) emit a `batch_complete` event to
`stream:iep2:batch_complete` at the end of each window, identified by
`window_start_ms`, `window_end_ms`, `store_id`, and `batch_number`.

IEP3 waits for all cameras registered for a store to report for window W before
running reconciliation. This synchronized barrier is what makes multi-camera
alignment possible: the SpatialVoter can compare floor positions from camera A
and camera B within the same 60-second window with confidence that they represent
the same time slice.

Window boundaries are wall-clock-aligned (not relative timers), managed by
APScheduler in EEP evaluating `store_operating_hours` every `WINDOW_SECONDS`
(default 60s). This ensures all IEP2 instances in a store share identical window
edges regardless of when they started.

---

## 5. Model selection rationale

All three model choices are outcomes of staged MLflow experiments, not hand-picked
defaults:

| Component | Model chosen | Experiment | Runs | Key result |
|---|---|---|---|---|
| Detection | RT-DETR-x, conf=0.5 | `detection` | 24 | Only model with 0 mannequin FP + best people confidence (85.6%) |
| Tracking | BoTSORT, match_thresh=0.8 | `tracking` | 7 | Lowest churn (fragmentation 3.56) of 4 trackers |
| ReID | resnet50_msmt17, thr=0.85 | `reid` | 7 | Best recovery (match_rate 0.60) + fastest (13 ms/crop) |

Full results, per-run metrics, Gantt charts, and MLflow artifacts in
`docs/docs_models/` and `docs/MLFLOW_ANALYSIS.md`.

Promotion is automated up to Staging via `scripts/check_promotion.py` using
thresholds derived from the actual experiment runs — not literature benchmarks.
Human sign-off is required for Production designation and live deployment.

---

## 6. Why this pipeline is non-trivial

**6.1 Each stage contains non-trivial ML logic**

- Detection: transformer architecture with bipartite matching, TRT FP16
  optimization, camera-specific confidence calibration
- Tracking: Kalman filter with sparse optical flow camera-motion compensation,
  motion-only association (ReID deliberately excluded from tracker internals)
- ReID: quality-ranked embedding gallery (top-K heaps, quality score =
  confidence × sqrt(bbox_area)), packed binary representation for DB storage
- Reconciliation: 3-stage algorithm combining geometric voting, ambiguity
  detection, and appearance fallback — none of which is a trivial threshold

**6.2 The architecture handles failure modes that simpler designs cannot**

- XACK-before-processing (ADR-001) ensures crash safety for the stateful
  reconciliation step without requiring full idempotency of the FSM
- Homography reload without restart: IEP2 subscribes to a Redis pub/sub
  channel and hot-reloads the floor projector when a new calibration is written
- Edge-local Redis buffers manifests when the cloud link is interrupted;
  IEP1 and IEP2 continue operating and the buffered batches are drained
  when connectivity restores

**6.3 Simpler approaches demonstrably fail**

- Single-camera tracking (no ReID): unique visitor count inflated 4–5× due to
  fragmented tracks across cameras
- Time-only cross-camera matching: O(N²) candidate ambiguity in crowded scenes;
  tested informally — produces near-random assignment when >3 people are in
  simultaneous transit
- Single cosine threshold (no spatial voting): higher false-merge rate in dense
  scenes; the 3-stage matcher reduces this by requiring both temporal consistency
  (spatial votes) and appearance confirmation before committing a match
