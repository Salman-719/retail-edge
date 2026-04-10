# Milestone 3: Vision Pipeline (Single Camera)

**Duration:** 2-3 weeks
**Dependencies:** M1
**Goal:** Person detection, single-camera tracking, ReID extraction, frame quality filters, and chunk-based processing on a single camera feed.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| YOLOv8 person detection | DONE | yolov8n, class=[0] person |
| Single-camera tracker (BoT-SORT) | DONE | botsort.yaml via ultralytics |
| Homography projection | DONE | pixel -> floor meters |
| Zone occupancy computation | DONE | dwell time + percent |
| Trajectory extraction | DONE | frameIdx, x, y, trackId |
| Live MJPEG stream | DONE | annotated frames in browser |
| Redis job state | DONE | progress, status, zone_occupancy |
| Heatmap generation | DONE | zone overlay on floor plan |
| ReID feature extractor (OSNet/FastReID) | NOT STARTED | |
| Employee enrollment capture | NOT STARTED | |
| Employee identification | NOT STARTED | |
| IEP1 frame quality filters | NOT STARTED | |
| IEP1 chunk assembly | NOT STARTED | |
| GPU optimization (FP16, batch) | NOT STARTED | |
| RT-DETR comparison benchmark | NOT STARTED | |

**Overall: ~50% complete**

---

## Remaining Tasks

### 1. ReID Feature Extractor

**File:** `services/iep2-vision/app/utils/reid.py` (NEW)

```python
Purpose:
- Load pretrained OSNet (torchreid) or FastReID model
- Extract 512-dim appearance embedding from person crop
- Provide cosine_similarity(emb_a, emb_b) helper

Interface:
  class ReIDExtractor:
      def __init__(self, model_name="osnet_x1_0")
      def extract(self, crop_bgr: np.ndarray) -> np.ndarray   # returns 512-dim vector
      def compare(self, emb_a, emb_b) -> float                # cosine similarity

Acceptance criteria:
  - Same person across frames: cosine similarity > 0.7
  - Different people: cosine similarity < 0.5
```

**Dependencies to add:** `torchreid` or `fastreid` in `services/iep2-vision/requirements.txt`

### 2. Employee Enrollment Capture

**Files:**

`services/iep2-vision/app/api/enrollment.py` (NEW):
```
POST /enrollment/{store_id}/employees/{employee_id}/capture
  Input: video_s3_key (enrollment walk video)
  Process:
    1. Run YOLO detection on sampled frames
    2. Extract person crops
    3. Run ReID extractor on each crop
    4. Average embeddings -> gallery embedding
    5. Store embedding in DB (employees.reid_embedding)
  Output: { status: "enrolled", embedding_dim: 512 }
```

`services/eep/app/api/employees.py` — add proxy to IEP2 enrollment endpoint.

### 3. Employee Identification in Tracker

**File:** `services/iep2-vision/app/utils/tracker.py`

Modify `run_tracking_job()`:
```
After each detection:
  1. Crop detected person from frame
  2. Extract ReID embedding via ReIDExtractor
  3. Compare against on-shift employee gallery (fetched from DB at job start)
  4. If cosine_similarity > 0.75: label as employee
  5. Else: label as customer
  6. Include person_type in trajectory data
```

### 4. IEP1 Frame Quality Filters

**File:** `services/iep1-ingestion/app/utils/quality.py` (NEW)

```python
Filters (each returns bool):
  is_blurry(frame)       -- Laplacian variance < threshold (e.g., 100)
  is_dark(frame)         -- mean pixel intensity < 30
  is_obstructed(frame)   -- edge density check or large uniform region
  is_frozen(frame, prev) -- SSIM > 0.99 with previous frame

Apply before saving frames. Log rejection rates as Prometheus metrics.
```

**Metrics to add in** `services/iep1-ingestion/app/core/metrics.py`:
```
frames_rejected_total (counter, labels: reason=[blur, dark, obstruction, frozen])
frames_accepted_total (counter)
```

### 5. IEP1 Chunk Assembly

**File:** `services/iep1-ingestion/app/utils/chunker.py` (NEW)

```python
Purpose: Split video/RTSP stream into 5-minute chunks with 30-second overlap.

class ChunkAssembler:
    CHUNK_DURATION = 300   # 5 minutes in seconds
    OVERLAP = 30           # 30 seconds overlap

    def process_video(self, video_path, camera_id, store_id):
        """Split video into chunks, apply quality filters, upload to S3."""
        For each chunk:
          1. Extract frames for [start, start+duration+overlap]
          2. Apply quality filters to each frame
          3. Write chunk video to temp file
          4. Upload to S3: stores/{store_id}/cameras/{camera_id}/chunks/{chunk_idx}.mp4
          5. Return chunk metadata (s3_key, start_time, end_time, frame_count)

    def process_rtsp(self, rtsp_url, camera_id, store_id):
        """Continuous RTSP ingest with rolling 5-min chunks."""
        (Future — for live camera feeds)
```

### 6. IEP1 -> IEP2 Integration

**File:** `services/iep1-ingestion/app/api/videos.py`

After video upload + chunking:
```
1. Split video into chunks via ChunkAssembler
2. For each chunk, POST to IEP2 /tracking/start with chunk s3_key
3. Return chunk metadata to caller
```

Alternatively, EEP orchestrates: upload to IEP1 -> dispatch chunks to IEP2.

### 7. GPU Optimization

**File:** `services/iep2-vision/app/utils/tracker.py`

```
Optimizations:
- Use model.predict(..., half=True) for FP16 inference
- Increase SAMPLE_EVERY from 3 to adaptive based on FPS
- Consider ONNX/TensorRT export for production
```

**File:** `docker-compose.yml` — add GPU passthrough:
```yaml
iep2-vision:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

### 8. Benchmark: YOLOv8 vs RT-DETR

**File:** `services/iep2-vision/benchmarks/detection_benchmark.py` (NEW)

```
Test with sample retail footage:
- YOLOv8n, YOLOv8s, YOLOv8m
- RT-DETR-l
Measure: mAP, latency per frame, GPU memory
Select best model for 5 FPS x 8 cameras target.
Document results in docsme/benchmarks/.
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `services/iep2-vision/app/utils/tracker.py` | YOLO + BoT-SORT tracking loop |
| `services/iep2-vision/app/utils/heatmap.py` | Zone heatmap rendering |
| `services/iep2-vision/app/utils/homography.py` | Pixel-to-floor projection |
| `services/iep2-vision/app/api/tracking.py` | Tracking endpoints |
| `services/iep2-vision/app/schemas.py` | IEP2 API contracts |
| `services/iep1-ingestion/app/api/videos.py` | Video upload + metadata |
| `services/iep1-ingestion/app/schemas.py` | IEP1 API contracts |

---

## Evaluation Criteria (must pass before M4)

- [ ] Person detector achieves >90% mAP on test retail footage
- [ ] Tracker produces continuous tracklets with <5% ID-switch rate
- [ ] ReID embeddings: same person cosine > 0.7, different person < 0.5
- [ ] Employee identification correctly matches enrolled employees >85%
- [ ] Frame quality filters reject >90% degraded frames, pass >95% clean frames
- [ ] Single-camera chunk pipeline completes in <90s for a 5-min chunk
- [ ] All unit and integration tests pass

## Re-iteration Triggers

- If detection poor on retail footage: fine-tune YOLO on 200-500 annotated retail frames
- If ID-switch rate >10%: already on BoT-SORT, tune `track_high_thresh`, `track_buffer`
- If ReID quality poor: try different backbone, ensure crop min 64x128 px
- If pipeline latency >5 min: profile bottleneck, try FP16, reduce frame rate
