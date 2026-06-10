# IEP2 — vision service

**Location:** `services/iep2_vision/`
**Runs on:** Edge device (one Kubernetes Deployment per camera)
**Depends on:** Edge-local Redis, YOLO service (ZMQ), ReID service (ZMQ), PostgreSQL (cloud)

## 1. Role and motivation

IEP2 owns all per-camera computer vision: detection, tracking, ReID embedding,
and floor projection. One Deployment per camera means:
- A crash or stall in one camera's worker does not affect any other camera.
- GPU resources (YOLO and ReID services) are shared across workers via ZMQ IPC,
  so model inference scales without reloading weights per camera.
- The worker can be started and stopped independently, without touching IEP1 or
  any other camera.

IEP2 does not decode video. It reads from Redis (the window manifest IEP1 wrote)
and from tmpfs (the JPEG frame files IEP1 placed there). IEP1 is the only writer
of both.

## 2. Input contract

- Reads from: `stream:iep1:{camera_id}` on edge-local Redis
- Consumer group: `iep2-{camera_id}`
- On startup, IEP2 runs **Phase A** (drain pending/un-ACKed messages from the
  consumer group's PEL) before entering **Phase B** (normal XREADGROUP blocking
  reads). This ensures batches from before a crash are processed exactly once.

## 3. Processing pipeline

For each frame in the window manifest:
1. **YOLO detection** — PUSH frame JPEG to `yolo_input.sock` via ZMQ; PULL
   response from `yolo_output_{camera_id}.sock`. Receives `bbox_xyxy` +
   `confidence` per person detection (class 0 only).
2. **BoTSORT tracking** — in-frame multi-object tracker (motion-only;
   `with_reid=False`). Assigns a stable `track_id` to each detection within
   this camera's continuous frame sequence.
3. **resnet50_msmt17 ReID** — PUSH person-crop JPEGs to `reid_input.sock` via
   ZMQ; PULL 2048-dim L2-normalised float32 embeddings per track. Embeddings
   are passed to `LocalIdentityManager` for in-camera gallery management.
4. **Local identity assignment** — `LocalIdentityManager` maps `track_id` →
   `local_id`. A `local_id` is a stable UUID backed by an atomic Redis counter
   (`iep2:id_counter:{camera_id}`). It survives IEP2 restarts because the
   counter lives in Redis; the `track_id → local_id` binding is in-process only.
5. **Homography projection** — `FloorProjector` maps pixel bbox centre to
   `(floor_x, floor_y)` in world metres using the camera's calibration
   (homography matrix, PnP, or TPS, depending on method). `NULL` if the camera
   has no calibration.
6. **Zone assignment** — Shapely polygon hit-test assigns `zone_id` to each
   floor coordinate. `NULL` if uncalibrated.

## 4. Output contract

### Written to PostgreSQL (asyncpg, within a single transaction per window)

- `tracking_history` — one row per `(local_id, timestamp_ms)`: bbox, confidence,
  area, `floor_x/y`, `zone_id`.
- `local_centroids` — UPSERT per `local_id`: top-quality ReID embeddings from
  `EmbeddingGallery` (init phase → sampled phase + novelty replacement).

Batch commit order: `tracking_history` → `local_centroids` → `batch_complete`
XADD → XACK → tmpfs frame cleanup. The XADD before XACK is intentional: if
IEP3 reads `batch_complete` before the DB transaction commits, IEP3 will wait
for the DB rows (asyncpg query will block until committed).

### Published to Redis (server Redis)

- `stream:iep2:batch_complete` — signals IEP3 that this camera's window is done.
  Contains `store_id`, `camera_id`, `window_id`, `batch_number`, frame count.
- `stream:iep2:live:{camera_id}` — per-frame live stream for browser preview
  (frame JPEG or S3 key + detections). Read by Live Bridge.

## 5. Error behavior

| Error condition | Behavior |
|---|---|
| YOLO service (ZMQ) unavailable at startup | ZMQ PUSH blocks if no consumer. IEP2 waits for Edge Agent's startup health check to confirm YOLO is SERVING before adding camera to IEP1, so frames only flow once YOLO is ready. |
| YOLO / ReID ZMQ timeout mid-window | Frame's detection/embedding is skipped; tracking continues with available data. Window is committed with whatever rows were successfully processed. |
| Camera uncalibrated (no homography) | `floor_x/y = NULL`, `zone_id = NULL`. Tracking history rows are still written; IEP3 can still do ReID-based identity matching. |
| PostgreSQL write fails | The asyncpg transaction is rolled back. `batch_complete` is NOT published. IEP2 logs the error and continues to the next window. The window's data is lost (no retry). |
| IEP2 crash mid-window | Phase A on next startup drains the un-ACKed manifest from the PEL and reprocesses it. The DB transaction from the crashed run was never committed (no partial rows). |
| IEP1 restart (tmpfs cleared) | Frame files referenced by a manifest may be missing. IEP2 skips missing files and commits whatever frames it could read. |

## 6. Independence evidence

- Separate Docker image per camera instance: `iep2_vision`.
- One k3s Deployment per camera — started by Edge Agent on `StartCamera`, deleted
  on `StopCamera`.
- Communicates only via Redis stream (reads IEP1), ZMQ sockets (calls YOLO/ReID),
  and PostgreSQL (writes). No shared memory or function calls with other IEP2s.
- Each camera has its own consumer group (`iep2-{camera_id}`) — one instance's
  reads never affect another's.

## 7. Metrics

Prometheus on `IEP2_METRICS_PORT` (default `:9201`):

| Metric | Description |
|---|---|
| `iep2_frames_total` | Frames processed |
| `iep2_detections_per_frame` | Histogram — detections per frame |
| `iep2_detection_confidence` | Histogram — bbox confidence scores |
| `iep2_tracks_active` | Gauge — active BoTSORT tracks |
| `iep2_track_age` | Histogram — track age at confirmation |
| `iep2_identity_switches` | Counter — track_id reassignments |
| `iep2_frame_latency_seconds` | Histogram — wall time per frame end-to-end |
| `iep2_errors_total` | Counter — frame-level errors |

## 8. Deployment

- **Image:** `ghcr.io/<owner>/retailvision/iep2` (multi-arch; edge/ARM64).
- **Cardinality:** 1 Deployment per active camera — created by Edge Agent.
- **GPU access:** shared via YOLO and ReID services over ZMQ unix sockets.
- **Dev:** `docker compose --profile dev up iep2_vision` with `CAMERA_ID` and
  `STORE_ID` env vars set. See README.md §IEP2 for the full command.
