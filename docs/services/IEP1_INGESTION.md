<!--
  Rubric: T2 — IEP1 independence and value (5%)
  This document proves IEP1 is architecturally independent and non-trivial.
-->

# IEP1 — ingestion service

**Location:** `services/iep1_ingestion/`
**Runs on:** Edge device (one daemon per device, handles all cameras)
**Depends on:** Edge-local Redis, tmpfs

## 1. Role and motivation

<!-- TODO: Why is ingestion a separate service from IEP2?
     What would break if they were merged?
     What does IEP1 own that IEP2 should not touch? -->

## 2. Input

- Source: RTSP stream URL or video file path (per camera, from EEP via gRPC)
- Sampling rate: `target_fps` (configurable per camera)
- Frame format: JPEG

## 3. Output contract

### Written to disk
- JPEG frames written to `tmpfs` at `/tmp/frames/{camera_id}/{window_id}/frame_{n}.jpg`

### Published to Redis
- Stream: `stream:iep1:{camera_id}`
- Message: window manifest (see `docs/SERVICE_CONTRACTS.md` §2)
- Trigger: at the end of each 60 s window

## 4. Error behavior

| Error condition | Behavior |
|---|---|
| RTSP connection lost | TODO: retry policy (N retries, backoff?) |
| RTSP reconnect fails after retries | TODO: emit error event? Log and skip window? |
| tmpfs full | TODO |
| Redis XADD fails | TODO |
| Camera not started (no gRPC StartCamera received) | TODO |

## 5. Independence evidence

- Separate Docker image: `iep1_ingestion`
- No direct code dependency on IEP2
- Communicates only via Redis stream (not shared memory or function calls)
- Can be restarted independently without affecting IEP2 state

## 6. Deployment

- One process per edge device (multiplexes all cameras)
- Managed by: k3s (or systemd?)
- Resource requirements: TODO (CPU, RAM, tmpfs size per camera)
