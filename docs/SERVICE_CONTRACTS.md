<!--
  Rubric: S1 — Service boundaries and contracts (3%)
-->

# Service contracts — RetailVision

## 1. Inter-service communication map

```
IEP1 (edge) ──► Redis stream:iep1:{camera_id} ──► IEP2 (edge, per camera)
IEP2 (edge) ──► Redis stream:iep2:batch_complete ──► IEP3 (cloud)
IEP2 (edge) ──► Redis stream:iep2:live:{cam_id} ──► Live Bridge (cloud)
EEP (cloud) ──► gRPC :50051 TLS ──► Edge Agent (edge) ──► k3s
```

## 2. Redis stream schemas

### stream:iep1:{camera_id} — window manifest

```json
{
  "window_id": "string",
  "camera_id": "string",
  "window_start_ms": "int64",
  "window_end_ms": "int64",
  "frame_paths": ["string"],
  "frame_timestamps_ms": ["int64"]
}
```
<!-- TODO: Verify fields match actual implementation -->

### stream:iep2:batch_complete

```json
{
  "camera_id": "string",
  "window_id": "string",
  "batch_number": "int",
  "track_count": "int"
}
```
<!-- TODO: Verify and complete fields -->

### stream:iep2:live:{camera_id}

```json
{
  "frame_jpeg_b64": "string",
  "detections": [],
  "timestamp_ms": "int64"
}
```
<!-- TODO: Complete detection schema -->

## 3. gRPC contracts

See `proto/agent.proto` and `proto/iep1_control.proto`.

### StartCamera RPC
<!-- TODO: Request fields, response fields, error codes -->

### StopCamera RPC
<!-- TODO: Request fields, response fields, error codes -->

## 4. REST API contracts

FastAPI auto-generates OpenAPI at `/docs` on the EEP service.

Key endpoints:

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | /auth/login | JWT login | None |
| POST | /auth/refresh | Refresh JWT | Bearer |
| GET | /stores | List stores | Bearer |
| POST | /stores | Create store | Bearer |
| GET | /stores/{slug}/cameras | List cameras | Bearer |
| TODO | TODO | TODO | TODO |

## 5. Database schema ownership

| Table | Owner service | Notes |
|---|---|---|
| tracking_history | IEP2 | Per-camera, per-frame detections |
| local_centroids | IEP2 | Per-camera ReID centroid embeddings |
| global_identities | IEP3 | Cross-camera identity records |
| global_local_mapping | IEP3 | Links global_id ↔ local_id ↔ camera_id |
| global_tracking_history | IEP3 | Canonical floor trajectory |
| stores / cameras / zones | EEP | Management plane |

## 6. Error response format

All EEP REST errors return:

```json
{
  "detail": "human-readable message",
  "code": "ERROR_CODE_STRING"
}
```
<!-- TODO: List all error codes used -->
