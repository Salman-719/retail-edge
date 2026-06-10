# YOLO / Detector Service

**Location:** `services/yolo_service/`
**Runs on:** Edge device (GPU; CPU fallback in dev)
**Depends on:** Edge-local Redis (device toggle), shared ZMQ unix sockets

## 1. Role

Runs person detection inference as a shared GPU service. IEP2 workers (one per
camera) do not load the model themselves — they PUSH frame batches over ZMQ to
this service, which returns bounding boxes. One shared service serves N IEP2
workers via batched inference, decoupling model loading from per-camera workers
and enabling GPU time-sharing.

## 2. Two variants

| File | When used | Model |
|---|---|---|
| `service.py` | Production (Jetson / NVIDIA GPU) | RT-DETR-x TRT FP16 engine (exported by `scripts/export_yolo_trt.py`) |
| `service_dev.py` | Dev / CPU x86 | RT-DETR-x `.pt` (default); YOLO11n `.pt` as low-compute fallback — set via `DETECTOR_MODEL` env var |

Both expose the **identical ZMQ wire protocol** — IEP2 cannot tell them apart.

`service_dev.py` additionally supports a live **CPU/GPU toggle** via Redis (see §5).

## 3. ZMQ architecture

```
IEP2 × N  ──PUSH──►  PULL  yolo_input.sock   (bind)
                          ↓ batch collector (up to MAX_BATCH_SIZE frames, BATCH_TIMEOUT_MS window)
                      RT-DETR-x inference  (person class only, class_id=0)
                          ↓ per-camera routing
IEP2 × N  ◄──PUSH──  PUSH  yolo_output_{camera_id}.sock  (connect, one socket per camera)
```

Messages are **msgpack-encoded** dicts. Request fields: `request_id`, `camera_id`,
`timestamp_ms`, `frame` (JPEG bytes). Response adds `detections` (list of
`{bbox_xyxy, confidence}`) and echoes the request identifiers.

## 4. Inference behaviour

- Filters to **class 0 (person) only** — other classes are discarded.
- Confidence threshold: `YOLO_CONF` (default `0.5`).
- IoU threshold: `YOLO_IOU` (default `0.45`).
- Batch size: up to `YOLO_MAX_BATCH_SIZE` (default `4` on CPU).
- Batch window: `YOLO_BATCH_TIMEOUT_MS` (default `500 ms`).

## 5. Device toggle (dev only)

`service_dev.py` reads the Redis key `inference:device` (`cpu` | `cuda` | `xpu` |
`gpu` | `auto`) every 2 s and resolves it against real hardware capability. The
active device is applied to the next inference batch without restart. Hardware
capability is published to `inference:capability:detector` (TTL 15 s) so the
frontend dev screen can report "GPU available".

## 6. TensorRT lazy-compile

If `EXPORT_TRT=true` and the service is running on GPU, a `.pt` model is
auto-exported to `.engine` on first run (~5 min). Subsequent starts load the
engine directly. Requires the Docker image built with `INSTALL_TRT=true`.

## 7. Health

gRPC `grpc.health.v1` server on two addresses:
- Unix: `YOLO_HEALTH_SOCK` (default `unix:///tmp/sockets/yolo_health.sock`)
- TCP: `YOLO_HEALTH_TCP_ADDR` (default `[::]:50052`)

Reports `NOT_SERVING` until model load + warmup complete, then `SERVING`. The Edge
Agent polls this before forwarding any `StartCamera` to IEP2.

## 8. Metrics

Prometheus on `:9400`, job label `detector`:

| Metric | Type | Description |
|---|---|---|
| `detector_inference_seconds` | Histogram | Batch inference latency |
| `detector_batch_size` | Histogram | Frames per batch |
| `detector_frames_total` | Counter | Total frames processed |
| `detector_detections_total` | Counter | Person detections returned |
| `detector_info{model=...}` | Gauge | Which model is loaded (value always 1) |

## 9. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `YOLO_INPUT_SOCK` | `ipc:///tmp/sockets/yolo_input.sock` | ZMQ PULL bind address |
| `YOLO_HEALTH_SOCK` | `unix:///tmp/sockets/yolo_health.sock` | gRPC health unix addr |
| `YOLO_HEALTH_TCP_ADDR` | `[::]:50052` | gRPC health TCP addr |
| `DETECTOR_MODEL` | `yolo11n.pt` (dev) | model file path |
| `YOLO_CONF` | `0.5` | confidence threshold |
| `YOLO_IOU` | `0.45` | IoU threshold |
| `YOLO_MAX_BATCH_SIZE` | `4` | max frames per batch |
| `YOLO_BATCH_TIMEOUT_MS` | `500` | batch collection window (ms) |
| `INFERENCE_DEVICE` | `cpu` | initial device (`cpu`/`cuda`/`xpu`) |
| `EXPORT_TRT` | `false` | auto-export .pt → TRT engine on first GPU run |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | for device toggle + capability publish |

## 10. Deployment

- **Edge (production):** `service.py` in the Jetson image (`Dockerfile`), TRT engine.
- **Dev (CPU):** `service_dev.py` via `docker-compose.dev.yml` override (`Dockerfile.dev`).
- **Dev (GPU):** same `service_dev.py` but CUDA PyTorch via `docker-compose.gpu.yml`.
- **Verify:** `docker exec retail-edge-redis-1 redis-cli GET inference:capability:detector`
  should return `{"cuda": true/false, ...}` once SERVING.
