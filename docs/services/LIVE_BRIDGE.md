# Live Bridge

**Location:** `services/live_bridge/`
**Runs on:** Cloud (one instance)
**Exposes:** HTTP/WebSocket :8010
**Depends on:** Server Redis (`stream:iep2:live:{camera_id}`), MinIO/S3

## 1. Role

Live Bridge converts the per-camera Redis live stream into WebSocket connections
for browser clients. It is the only path by which live frame data reaches the
browser. EEP and the pipeline services have no knowledge of it.

## 2. Input

IEP2 writes a message to `stream:iep2:live:{camera_id}` on the server Redis for
every processed frame. Each message is a JSON payload with one of two frame
transports:

- **Embed mode** (dev): `frame_b64` — base64-encoded JPEG, no S3 round-trip.
- **S3 mode** (prod): `s3_key` — the object key in MinIO/S3; Live Bridge presigns
  it to a short-lived URL before forwarding.

Both modes include `camera_id`, `timestamp_ms`, and a `detections` array (bboxes).

## 3. WebSocket endpoint

```
GET /ws/live/{camera_id}
```

One background asyncio task (`_reader_task`) reads the Redis stream for a given
`camera_id`. The task starts when the first client connects and is cancelled when
the last client disconnects. Multiple clients may connect to the same camera
simultaneously — each gets its own `asyncio.Queue(maxsize=32)`.

Slow clients drop frames silently (`queue.put_nowait`, never blocks). The reader
task never blocks the event loop: S3 presigning is awaited, Redis reads use
`aioredis` XREAD.

## 4. Frame payload sent to the browser

```json
{
  "camera_id": "<uuid>",
  "timestamp_ms": 1234567890,
  "detections": [{"bbox_xyxy": [...], "confidence": 0.91}],
  "frame_url": "https://minio/..."   // S3 mode
  // OR
  "frame_b64": "<base64 JPEG>"       // embed mode
}
```

If neither `s3_key` nor `frame_b64` is present (overlay-only mode), `frame_url`
is `null` and only detections are forwarded.

## 5. Health

```
GET /health  →  {"status": "ok"}
```

## 6. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | reads `stream:iep2:live:{cam}` |
| `S3_ENDPOINT_URL` | required | MinIO/S3 endpoint for presigned URL generation |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | required | S3 credentials |
| `PRESIGNED_URL_EXPIRY` | `30` | seconds until presigned URL expires |

## 7. Deployment

- **Image:** `ghcr.io/<owner>/retailvision/live_bridge`
- **Cloud:** single Deployment, exposed via Ingress at `/ws/` (nginx proxy\_pass
  with `Upgrade: websocket`). See `docs/operations/DEPLOYMENT_GUIDE.md`.
- **Dev:** `docker compose up live_bridge` — smoke test: `curl http://localhost:8010/health`
