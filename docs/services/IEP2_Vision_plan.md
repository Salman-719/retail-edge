# IEP2 — Vision (Detection, Tracking, ReID, MLOps)

**Role:** The compute-heavy service. Runs YOLOv8 person detection + BoT-SORT tracking on a single camera, projects pixel coordinates to floor metres via homography, computes zone occupancy, extracts ReID embeddings, reconciles track IDs across chunk boundaries and across cameras, and owns the ReID fine-tuning pipeline.

**Source:** `services/iep2-vision/`
**Primary port:** 8002
**Dependencies:** PostgreSQL (sync + async), Redis, S3, GPU (NVIDIA, Linux), MLflow (M7)

---

## Contract (what IEP2 exposes)

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /health` | Liveness | DONE |
| `POST /tracking/start` | Start tracking job on a chunk (`TrackingStartRequest`) | DONE |
| `GET /tracking/progress/{camera_id}` | Poll progress / zone occupancy (`TrackingProgressResponse`) | DONE |
| `GET /tracking/trajectory/{camera_id}` | Fetch final trajectory (`TrajectoryResponse`) | DONE |
| `GET /tracking/stream/{camera_id}` | MJPEG preview with detections | DONE |
| `POST /enrollment/{store_id}/employees/{employee_id}/enroll` | Build ReID gallery from enrollment walk (`EnrollmentRequest`/`Response`) | DONE |
| `POST /mlops/train` · `/evaluate` · `/promote` · `GET /mlops/status` | Fine-tune + registry lifecycle | NOT STARTED (M7) |
| `GET /metrics` | Prometheus | PARTIAL |

**Schemas:** `services/iep2-vision/app/schemas.py` (`TrackingStartRequest`, `TrackingProgressResponse`, `TrajectoryPoint`, `TrajectoryResponse`, `ZoneOccupancy`, `EnrollmentRequest`, `EnrollmentResponse`).

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| YOLOv8 person detection (`class=[0]`) | DONE | `yolov8n` |
| BoT-SORT tracker | DONE | `botsort.yaml` via ultralytics |
| Homography projection (pixel→floor m) | DONE | `app/utils/homography.py` |
| Zone occupancy (dwell seconds + %) | DONE | |
| Trajectory extraction (frameIdx, x, y, trackId) | DONE | |
| Live MJPEG stream with overlays | DONE | |
| Redis job state | DONE | `tracking:job:{camera_id}` |
| Heatmap render (zone overlay) | DONE | `app/utils/heatmap.py` |
| ReID extractor (MobileNetV3 backbone) | DONE | `app/utils/reid.py` |
| Employee gallery load + per-track matching | DONE | `_load_employee_gallery()` in tracker |
| `personType` / `employeeId` in trajectory records | DONE | |
| Enrollment endpoint | DONE | `app/api/enrollment.py` |
| Sync DB engine for background thread | DONE | `sync_engine` in `app/core/database.py` |
| GPU passthrough (docker-compose) | DONE (commented for macOS) | uncomment on Linux |
| FP16 inference (`half=True`) | NOT STARTED | M3 polish |
| Adaptive `SAMPLE_EVERY` | NOT STARTED | M3 polish |
| YOLOv8 vs RT-DETR benchmark | NOT STARTED | M3 |
| Chunk carryover (cross-chunk ID continuity) | NOT STARTED | M4 |
| Warm-up replay on overlap | NOT STARTED | M4 |
| Reconciler (Hungarian over ReID+space) | NOT STARTED | M4 |
| Cross-camera ReID association | NOT STARTED | M4 |
| Entrance/exit detection | NOT STARTED | M4 |
| MLflow server + experiment | NOT STARTED | M7 |
| Golden dataset (S3 + manifest) | NOT STARTED | M7 |
| Data collector (high-confidence crops) | NOT STARTED | M7 |
| Fine-tune script + evaluate + promote/rollback | NOT STARTED | M7 |
| Custom metrics: `reid_cosine_distance`, `detection_confidence`, `track_fragmentation_rate` | NOT STARTED | M8 |

**Overall: ~50% of IEP2 scope complete.**

---

## Implementation Tasks

### A. Single-camera pipeline polish (M3)

1. **FP16 inference** — in `app/utils/tracker.py` set `model.predict(..., half=True)` when CUDA available; gate behind env `IEP2_FP16=1`.
2. **Adaptive sampling** — current `SAMPLE_EVERY=3` is static; compute from source FPS to target 10 effective FPS.
3. **Benchmark** — `services/iep2-vision/benchmarks/detection_benchmark.py` runs YOLOv8{n,s,m} + RT-DETR-l on a fixed retail clip, writes mAP / latency / VRAM to `docs/benchmarks/detection.md`.

### B. Chunk continuity (M4)

1. **CarryoverPayload** — `app/utils/carryover.py` (NEW):
   ```
   dataclass CarryoverPayload:
       tracker_states: dict          # BoT-SORT internal per track
       reid_embeddings: dict         # track_id -> 512-dim vec
       id_mapping: dict              # local_tid -> global_pid
       last_positions: dict          # track_id -> (x, y, ts)
       serialize()/deserialize()  (msgpack via Redis)
   ```
   Redis key `carryover:{camera_id}`, TTL = 2 × chunk_duration.

2. **Warm-up replay** — modify `run_tracking_job()`:
   ```
   Phase 1: load carryover (if any)
   Phase 2: replay last 30 s of prev chunk — do NOT emit results
   Phase 3: run new frames → emit trajectory + occupancy
   Phase 4: serialize carryover at end of chunk
   ```

3. **Reconciler** — `app/utils/reconciler.py` (NEW): Hungarian (`scipy.optimize.linear_sum_assignment`) over a cost matrix combining cosine-distance (ReID) + spatial distance (< 3 m) + temporal gap (< overlap_duration).

### C. Cross-camera association (M4)

**File:** `app/utils/cross_camera.py` (NEW)

```
associate_across_cameras(camera_results: list[dict]) -> dict
  1. build N×M cosine-distance matrix between per-camera ReID means
  2. spatial plausibility: walking speed cap 1.5 m/s between cameras
  3. Hungarian optimal assignment
  4. return {camera_id: {local_id: global_pid}}
```

Called by EEP orchestrator after all cameras finish a chunk.

### D. Entrance/exit detection (M4)

**File:** `app/utils/entrance.py` (NEW)

- Entrance zones flagged by `zone.type == "entrance"`.
- Compute per-person first/last appearance in entrance zones, velocity vector → classify `enter`/`exit`.
- Emit events `{person_id, direction, timestamp}` to IEP3 via orchestrator.

### E. MLOps pipeline (M7)

All files under `services/iep2-vision/training/` + `app/api/mlops.py`.

1. **MLflow** — add service to `docker-compose.yml` (postgres backend + S3/MinIO artifact root), create `mlflow` DB in init script.
2. **Golden dataset** — `services/iep2-vision/data/golden/` with ≥ 20 crops/employee from multiple angles, ≥ 5 negatives; manifest `metadata.json`; upload to `s3://retailvision/datasets/golden/v1/`. Rule: **never used for training**.
3. **Data collector** — `app/utils/data_collector.py`: save crops with confidence ≥ 0.85, ≥ 64×128 px, not blurry; cap 500/employee; write to S3 `datasets/training/{version}/employee_{id}/`.
4. **Fine-tune** — `training/finetune_reid.py`: torchreid `ImageTripletEngine`, log params/metrics/artifact with MLflow.
5. **Evaluate** — `training/evaluate_reid.py`: Rank-1, mAP, per-employee accuracy, CMC curve → MLflow.
6. **Promote** — `training/promote.py`: criteria (Rank-1 +1 % absolute, mAP ≥ −0.5 %, no per-employee drop > 5 %); set stage `Production` in registry.
7. **Rollback** — `training/rollback.py`: watch `reid_cosine_distance` Prometheus histogram; if mean shifts > 2σ for > 10 min, swap stages.
8. **API** — `app/api/mlops.py`: `POST /mlops/train|evaluate|promote`, `GET /mlops/status`.

### F. Observability (M8)

Add to `app/core/metrics.py`:

```
reid_cosine_distance       Histogram
detection_confidence       Histogram
track_fragmentation_rate   Gauge   # ID switches per 100 frames
active_tracking_jobs       Gauge   (already exists)
```

---

## ReID Reference

Current implementation (`app/utils/reid.py`):

| Item | Value |
|------|-------|
| Backbone | `torchvision` MobileNetV3-Large, classifier replaced with `nn.Identity()` |
| Input | BGR crop → 256×128 resize, ImageNet normalise |
| Output | L2-normalised embedding |
| API | `extract(crop)`, `extract_batch(crops)`, `cosine_similarity(a,b)`, `match_against_gallery(emb, gallery, thresh=0.75)` |

Enrollment (`app/api/enrollment.py`):
1. Download enrollment walk video from S3.
2. Sample every Nth frame, run YOLO.
3. Crop detections, call `extract_batch`.
4. Mean-pool embeddings → store in `employees.gallery_embeddings` (JSON).

Tracker integration (`app/utils/tracker.py`):
- `_load_employee_gallery(store_id)` at job start builds `{employee_id: mean_embedding}` via `sync_engine`.
- Per track: crop → ReID → compare against gallery; if cosine ≥ threshold, attach `personType="employee"` + `employeeId`, else `personType="customer"`.

---

## Evaluation Criteria

- [x] Same-person cosine similarity > 0.7 across frames
- [x] Different-person cosine < 0.5
- [ ] Detection mAP > 0.90 on retail footage
- [ ] ID-switch rate < 5 % single-camera
- [ ] Employee match accuracy > 85 %
- [ ] 5-min chunk processes in < 90 s (single camera)
- [ ] Cross-chunk ID continuity > 90 %
- [ ] Cross-camera association > 80 %
- [ ] MLflow shows reproducible evaluation metrics
- [ ] Promotion only fires when all criteria pass
- [ ] Rollback fires on simulated degradation

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app |
| `app/schemas.py` | All I/O contracts |
| `app/api/tracking.py` | Start/progress/trajectory/stream |
| `app/api/enrollment.py` | Employee ReID enrollment |
| `app/utils/tracker.py` | YOLO + BoT-SORT + ReID loop |
| `app/utils/reid.py` | `ReIDExtractor` |
| `app/utils/homography.py` | Pixel→floor projection |
| `app/utils/heatmap.py` | Zone heatmap render |
| `app/core/database.py` | async + sync engines |
| `app/core/metrics.py` | Prometheus metrics |
| `training/*` (M7) | Fine-tune / evaluate / promote / rollback |
| `benchmarks/detection_benchmark.py` (M3) | Detection model comparison |

---

## Re-iteration Triggers

- Detection weak on retail footage → fine-tune YOLO on 200–500 annotated retail frames
- ID-switch > 10 % → tune BoT-SORT `track_high_thresh`, `track_buffer`
- ReID quality poor → swap backbone (OSNet / FastReID), enforce crop ≥ 64×128
- Pipeline > 5 min/chunk → FP16, batch detection, reduce effective FPS
- Cross-chunk continuity weak → widen overlap 30 s → 45–60 s
- Rollback too sensitive → raise σ threshold or window
