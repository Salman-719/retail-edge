<!--
  Rubric: T3 — IEP2 independence and value (5%)
  This document proves IEP2 is architecturally independent and non-trivial.
-->

# IEP2 — vision service

**Location:** `services/iep2_vision/`
**Runs on:** Edge device (one Kubernetes Deployment per camera)
**Depends on:** Edge-local Redis, YOLO service (ZMQ), OSNet service (ZMQ), PostgreSQL (cloud), MinIO

## 1. Role and motivation

<!-- TODO: Why is per-camera vision a separate service from ingestion?
     Why one deployment per camera rather than one process for all cameras?
     What non-trivial work does IEP2 do that justifies its existence? -->

## 2. Input contract

- Reads from: `stream:iep1:{camera_id}` (window manifest)
- Consumer group: `iep2-{camera_id}`

## 3. Processing pipeline

For each frame in the window manifest:
1. **YOLO detection** — calls YOLO service via ZMQ unix socket, receives bounding boxes + confidence scores
2. **ByteTrack tracking** — assigns stable `local_id` to each detected person within this camera's frame sequence
3. **OSNet ReID** — calls OSNet service via ZMQ unix socket, extracts 512-dim appearance embedding per track
4. **Homography projection** — maps bounding box pixel coordinates to floor `(floor_x, floor_y)` using per-camera calibration matrix
5. **Zone assignment** — Shapely polygon hit-test to assign `zone_id` to each floor coordinate

## 4. Output contract

### Written to PostgreSQL
- Table: `tracking_history` — one row per (local_id, timestamp_ms)
- Table: `local_centroids` — updated ReID centroid per local_id

### Published to Redis
- Stream: `stream:iep2:batch_complete` — signals IEP3 that this camera's window is done
- Stream: `stream:iep2:live:{camera_id}` — live frame + detections for browser preview

## 5. Error behavior

| Error condition | Behavior |
|---|---|
| YOLO service (ZMQ) unavailable | TODO: retry N times, then skip frame? skip window? |
| OSNet service (ZMQ) unavailable | TODO |
| Camera not calibrated (no homography matrix) | floor_x/y = NULL, zone_id = NULL — still processes |
| PostgreSQL write fails | TODO |
| Window manifest missing frames | TODO |

## 6. Independence evidence

- Separate Docker image per camera instance: `iep2_vision`
- One k3s Deployment per camera (started by Edge Agent via EEP's StartCamera command)
- No shared state with IEP1 (reads only from Redis stream)
- No shared state with other IEP2 instances (each camera has its own consumer group)
- Can be killed and restarted mid-window — IEP3 handles incomplete batches

## 7. Deployment

- **Cardinality:** 1 Deployment per active camera
- **Started by:** Edge Agent on receipt of gRPC `StartCamera` from EEP
- **GPU access:** Shares YOLO service and OSNet service (both GPU-backed, via ZMQ)
- **Resource requirements:** TODO (CPU, RAM per instance)
