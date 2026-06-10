# IEP1 — ingestion service

**Location:** `services/iep1_ingestion/`
**Runs on:** Edge device (one daemon per device, handles all cameras)
**Depends on:** Edge-local Redis, tmpfs (`TMPFS_FRAME_ROOT`)

## 1. Role and motivation

IEP1 is a single long-running daemon that multiplexes all cameras on the device.
It owns two concerns IEP2 must not touch: (1) raw video acquisition (cv2 capture,
RTSP reconnect, frame pacing) and (2) tmpfs frame lifecycle (write, accumulate,
clean up after the window is ACKed).

Keeping ingestion separate from IEP2 means:
- One IEP2 crash or restart does not affect the frame capture loop for that camera
  or any other camera — IEP1 keeps writing; IEP2 drains the backlog on restart.
- Cameras can be added and removed via gRPC without restarting any vision workers.
- The heavy cv2/OpenCV dependency is isolated to one image; IEP2's image carries
  only the vision stack.

IEP2 never opens the RTSP stream directly. It reads only from Redis and tmpfs.

## 2. Daemon architecture

`daemon.py` runs a single gRPC server (two unix sockets) and dispatches calls to
`CameraWorker` instances. Each `CameraWorker` has:
- A dedicated **OS thread** running the blocking `cv2.VideoCapture` loop (paced
  to `target_fps` by stride — every Nth decoded frame is kept).
- An **asyncio task** running the window accumulator that collects frames into a
  60 s window, writes the manifest to Redis, and cleans up tmpfs after ACK.

The two parts communicate via a bounded `asyncio.Queue(maxsize=FRAME_QUEUE_SIZE,
default=30)`. If the queue is full, frames are dropped (IEP1_FRAMES_DROPPED
counter incremented) — the pipeline degrades gracefully rather than backing up.

gRPC sockets:
- `IEP1_CONTROL_SOCK` — `Iep1Control` service (AddCamera, RemoveCamera, GetStatus)
  **and** `grpc.health.v1`
- `IEP1_HEALTH_SOCK` — `grpc.health.v1` only (watched by Edge Agent)

## 3. Input

Each camera is added via `AddCamera` gRPC RPC (called by Edge Agent on
`StartCamera`). The RPC carries:

| Field | Description |
|---|---|
| `camera_id` | UUID matching `physical_cameras.id` |
| `rtsp_url` | RTSP stream URL or local file path (`cv2.VideoCapture` accepts both) |
| `target_fps` | Desired capture rate; IEP1 strides the decoded stream to match |
| `window_seconds` | Batch window length — must match IEP2 and IEP3 |
| `store_id` | Passed through to the manifest |

## 4. Output contract

### Written to tmpfs

JPEG frames at `{TMPFS_FRAME_ROOT}/{camera_id}/{timestamp_ms}.jpg`
(default tmpfs root: `/dev/shm/frames`).

### Published to Redis

- Stream: `stream:iep1:{camera_id}` on edge-local Redis
- Message: a **window manifest** JSON object: list of frame paths + timestamps for
  the completed 60 s window, plus `camera_id`, `store_id`, `window_id`,
  `batch_number`.
- Trigger: end of each `window_seconds` window.
- `STREAM_MAXLEN = 1000` — old entries are trimmed automatically.

## 5. Error behavior

| Error condition | Behavior |
|---|---|
| RTSP connection lost | `cv2.VideoCapture.read()` returns `False`. Worker logs a warning, re-opens the capture (up to `MAX_OPEN_RETRIES` attempts with back-off), then exits the capture thread. The window task completes the partial window with whatever frames were captured and publishes the manifest. |
| cv2 frame decode / JPEG encode fails | Frame skipped, `IEP1_ENCODE_ERRORS` counter incremented. Window continues with remaining frames. |
| Frame queue full | Frame dropped, `IEP1_FRAMES_DROPPED` counter incremented. Never blocks the capture thread. |
| Redis `XADD` fails | Exception propagated; window task logs ERROR and exits. The camera remains registered; the next window attempt will retry. |
| tmpfs full | File write raises `OSError`; frame is skipped. IEP1 continues running. |
| `AddCamera` for already-active camera | Returns `success=False, error="already_active"`. |
| EEP or Edge Agent restart | IEP1 keeps running. Edge Agent's `_restore_active_cameras()` re-adds cameras to IEP1 by reading ConfigMaps. |

## 6. Metrics

Prometheus on `IEP1_METRICS_PORT` (default `:9200`):

| Metric | Description |
|---|---|
| `iep1_active_cameras` | Gauge — number of CameraWorkers running |
| `iep1_frames_total{camera_id}` | Counter — frames successfully written to tmpfs |
| `iep1_frames_dropped_total{camera_id}` | Counter — frames dropped (queue full) |
| `iep1_encode_errors_total{camera_id}` | Counter — JPEG encode failures |
| `iep1_publish_latency_seconds` | Histogram — time to write manifest + XADD |

## 7. Deployment

- **Image:** `ghcr.io/<owner>/retailvision/iep1` (multi-arch; edge/ARM64).
- **Cardinality:** exactly one per edge device (handles all cameras on that device).
- **Managed by:** k3s Deployment (not per-camera; always running).
- **Dev:** started by `docker compose up iep1-daemon`. The control socket is at
  `/tmp/iep1-sockets/iep1_control.sock` inside the container.
