# IEP1 — Video Ingestion

**Role:** Accept video uploads (and, later, RTSP streams), extract metadata, enforce frame-quality filters, split into overlapping chunks, and hand off to IEP2 via S3 keys.

**Source:** `services/iep1-ingestion/`
**Primary port:** 8001
**Dependencies:** S3 (MinIO in local), Redis (job state), IEP2 (chunk dispatch)

---

## Contract (what IEP1 exposes)

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /health` | Liveness | DONE |
| `POST /videos/{store_id}/cameras/{camera_id}/upload` | Upload raw video, extract metadata → `VideoUploadResponse` | DONE |
| `POST /videos/{store_id}/cameras/{camera_id}/chunk` | Chunk uploaded video into 5-min segments with 30 s overlap → `ChunkResponse` | DONE |
| `POST /videos/{store_id}/cameras/{camera_id}/rtsp` | (Stretch) Continuous RTSP ingest, emit rolling chunks | NOT STARTED |
| `GET /metrics` | Prometheus metrics | PARTIAL (scrape target not yet wired) |

**Schemas:** `services/iep1-ingestion/app/schemas.py` (`VideoUploadResponse`, `ChunkInfo`, `ChunkResponse`).

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| FastAPI skeleton + `/health` | DONE | |
| Typed Pydantic I/O | DONE | `schemas.py` |
| S3 upload (multipart) | DONE | uses shared S3 client |
| Video metadata extraction (fps, duration, resolution) | DONE | OpenCV |
| Frame quality filters (blur, dark, obstruction, frozen) | DONE | `app/utils/quality.py` |
| Prometheus metrics: `frames_rejected_total`, `frames_accepted_total` | DONE | `app/core/metrics.py` |
| Chunk assembler (5 min + 30 s overlap) | DONE | `app/utils/chunker.py`, `chunk_video()` |
| `POST /videos/.../chunk` endpoint | DONE | |
| Auto-dispatch to IEP2 per chunk | NOT STARTED | M3 gap |
| RTSP continuous ingest | NOT STARTED | Stretch |
| Prometheus scrape target in `monitoring/prometheus.yml` | NOT STARTED | M8 |
| Upload-retry / backoff on S3 failure | NOT STARTED | M8 |

**Overall: ~80%.**

---

## Remaining Tasks

### 1. Auto-dispatch chunks to IEP2

**File:** `services/iep1-ingestion/app/api/videos.py`

After `chunk_video()` returns the chunk list, for each chunk POST to IEP2 `/tracking/start` with the chunk's S3 key. Alternatively, have EEP orchestrate (recommended — matches `orchestrator.py` in EEP plan). Pick one owner and document; current decision: **EEP orchestrator owns dispatch**, IEP1 just returns chunk metadata.

### 2. RTSP ingest (stretch)

**File:** `services/iep1-ingestion/app/utils/rtsp_ingester.py` (NEW)

```
class RTSPIngester:
    """OpenCV VideoCapture loop, 5-min rolling chunk writer."""
    - reconnect with backoff on stream drop
    - apply quality filter per frame before writing
    - emit chunk metadata to Redis pub/sub on rollover
```

Endpoint `POST /videos/.../rtsp` starts a background task; state in Redis `ingest:rtsp:{camera_id}` (TTL = chunk_duration × 2).

### 3. Prometheus scrape

**File:** `monitoring/prometheus.yml` — add:
```yaml
- job_name: 'iep1-ingestion'
  static_configs:
    - targets: ['iep1-ingestion:8001']
```

### 4. S3 retry + backoff

On upload failure: queue (Redis list `ingest:s3:retry`), retry with exponential backoff (1 s, 2 s, 4 s, 8 s), give up after 5 attempts and surface 502 via EEP error handler.

---

## Quality Filter Reference

Implemented in `app/utils/quality.py`. All defaults tunable via env:

| Filter | Method | Default threshold | Reject when |
|--------|--------|-------------------|-------------|
| Blur | Laplacian variance | 100 | variance < threshold |
| Dark | Mean intensity | 30 | mean < threshold |
| Obstruction | Histogram max bin fraction | 0.60 | one bin > 60% of pixels |
| Frozen | Normalised cross-correlation vs previous frame | 0.99 | NCC > threshold |

`check_frame()` returns `(ok: bool, reason: Optional[str])` and increments the Prometheus counter.

---

## Chunk Contract

Defined in `app/utils/chunker.py`:

```
CHUNK_DURATION = 300      # 5 minutes
OVERLAP        = 30       # 30 seconds

chunk_video(video_s3_key, camera_id, store_id) -> ChunkResponse
  - downloads video to temp
  - iterates [start, start+CHUNK_DURATION+OVERLAP]
  - applies quality filter
  - writes chunk mp4, uploads to S3 key:
      stores/{store_id}/cameras/{camera_id}/chunks/{chunk_idx}.mp4
  - returns list[ChunkInfo] = {s3_key, start_time, end_time, frame_count}
```

---

## Evaluation Criteria

- [x] Typed schemas validate on bad input
- [x] Upload of a 120 s sample video produces valid `VideoUploadResponse`
- [x] Quality filter rejects synthetic blurry/black/frozen frames
- [ ] Chunker splits a 20-min sample into 4 overlapping chunks in < 60 s
- [ ] Prometheus shows `frames_rejected_total{reason=...}` with real values
- [ ] S3 upload failure retries and finally surfaces a 502 without crashing the service

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app |
| `app/schemas.py` | `VideoUploadResponse`, `ChunkInfo`, `ChunkResponse` |
| `app/api/videos.py` | Upload + chunk endpoints |
| `app/utils/quality.py` | Frame quality filters |
| `app/utils/chunker.py` | `chunk_video()` |
| `app/core/metrics.py` | Prometheus counters |
| `app/core/s3.py` | S3 client wrapper |

---

## Re-iteration Triggers

- Quality filter rejects too aggressively → log per-reason rates, relax thresholds
- Chunker slow → move to ffmpeg subprocess with `-c copy` (stream copy, no re-encode)
- RTSP stream drops → add exponential reconnect, alarm after 3 failures
