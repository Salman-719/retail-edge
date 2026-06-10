# ReID Service

**Location:** `services/reid_service/`
**Runs on:** Edge device (GPU; CPU fallback in dev)
**Depends on:** Edge-local Redis (device toggle), shared ZMQ unix sockets

## 1. Role

Runs ReID (re-identification) embedding inference as a shared GPU service. IEP2
workers PUSH person-crop batches over ZMQ to this service, which returns
2048-dimensional L2-normalised float32 embeddings. One shared service serves N
IEP2 workers via batched inference.

The embeddings feed two consumers: IEP2's `LocalIdentityManager` (in-camera track
gallery) and, via `local_centroids` in Postgres, IEP3's cosine-similarity matcher
for cross-camera identity linking.

## 2. Two variants

| File | When used | Backend |
|---|---|---|
| `service.py` | Production (Jetson / NVIDIA GPU) | TensorRT or ONNX |
| `service_dev.py` | Dev / CPU x86 | resnet50_msmt17 via boxmot `ReidAutoBackend` (PyTorch) |

Both expose the **identical ZMQ wire protocol**.

## 3. ZMQ architecture

```
IEP2 × N  ──PUSH──►  PULL  reid_input.sock   (bind)
                          ↓ batch collector (up to MAX_BATCH_SIZE crops, BATCH_TIMEOUT_MS window)
                      resnet50_msmt17 inference + L2 normalisation
                          ↓ per-camera routing
IEP2 × N  ◄──PUSH──  PUSH  reid_output_{camera_id}.sock  (connect, one socket per camera)
```

Messages are **msgpack-encoded** dicts. Request fields: `request_id`, `camera_id`,
`track_id`, `timestamp_ms`, `crop` (JPEG bytes of the person bounding-box crop).
Response echoes all identifiers and adds `embedding` (2048-dim float32, packed as
raw bytes — 8192 bytes).

## 4. Preprocessing

Each JPEG crop is resized to **128 × 256 px**, converted to float32, and
normalised with ImageNet mean/std (`[0.485, 0.456, 0.406]` /
`[0.229, 0.224, 0.225]`). Layout is CHW float32, batched as `[B, 3, 256, 128]`.

## 5. Output

- **Dimension:** 2048 (resnet50_msmt17 output; NOT the 512-dim OSNet legacy value).
- **Normalisation:** L2 before packing — embeddings always have unit norm.
- **Packing:** raw `float32.tobytes()`, 8192 bytes per embedding.

## 6. Device toggle (dev only)

`service_dev.py` reads `inference:device` from Redis every 2 s (same key as the
YOLO service). When device changes, the PyTorch model is moved to the new device
on the next inference call. Capability is published to
`inference:capability:reid` (TTL 15 s).

## 7. Health

gRPC `grpc.health.v1` server on two addresses:
- Unix: `REID_HEALTH_SOCK` (default `unix:///tmp/sockets/reid_health.sock`)
- TCP: `REID_HEALTH_TCP_ADDR` (default `[::]:50053`)

Reports `NOT_SERVING` until model load + warmup complete, then `SERVING`. The Edge
Agent polls this before forwarding any `StartCamera` to IEP2.

## 8. Metrics

Prometheus on `REID_METRICS_PORT` (default `:9401`), job label `reid`:

| Metric | Type | Description |
|---|---|---|
| `reid_crops_processed_total` | Counter | Total person crops processed |
| `reid_errors_total` | Counter | Crops that caused inference errors |
| `reid_inference_seconds` | Histogram | Wall-clock time per batch |
| `reid_batch_size` | Histogram | Crops per batch |
| `reid_embedding_norm` | Histogram | L2 norm of raw (pre-normalisation) embeddings |

## 9. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `REID_INPUT_SOCK` | `ipc:///tmp/sockets/reid_input.sock` | ZMQ PULL bind address |
| `REID_HEALTH_SOCK` | `unix:///tmp/sockets/reid_health.sock` | gRPC health unix addr |
| `REID_HEALTH_TCP_ADDR` | `[::]:50053` | gRPC health TCP addr |
| `REID_MODEL_PATH` | `resnet50_msmt17.pt` | model weights path |
| `REID_MAX_BATCH_SIZE` | `8` | max crops per batch |
| `REID_BATCH_TIMEOUT_MS` | `200` | batch collection window (ms) |
| `REID_METRICS_PORT` | `9401` | Prometheus metrics port |
| `INFERENCE_DEVICE` | `cpu` | initial device (`cpu`/`cuda`) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | for device toggle + capability publish |

## 10. Deployment

- **Edge (production):** `service.py` in the Jetson image (`Dockerfile`).
- **Dev (CPU):** `service_dev.py` via `docker-compose.dev.yml` (`Dockerfile.dev`).
- **Dev (GPU):** same `service_dev.py` + CUDA PyTorch via `docker-compose.gpu.yml`.
- **Verify:** `docker exec retail-edge-redis-1 redis-cli GET inference:capability:reid`
  should return `{"cuda": true/false, ...}` once SERVING.
