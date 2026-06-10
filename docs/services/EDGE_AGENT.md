# Edge Agent

**Location:** `services/edge_agent/`
**Runs on:** Edge device (systemd service)
**Depends on:** EEP (gRPC :50051), IEP1 (unix socket), YOLO service, ReID service, k3s or Docker

## 1. Role

The Edge Agent is the thin gRPC relay between the cloud control plane (EEP) and
the edge compute backend (k3s or Docker). It translates `StartCamera` /
`StopCamera` commands from EEP into actual container lifecycle operations, and
reports container health + heartbeats back to EEP over the same persistent
bidirectional stream.

It owns the per-camera IEP2 lifecycle. IEP2 pods/containers are never started or
stopped by anything else.

## 2. Backends

The agent selects its backend at startup:

1. **k3s** (`k8s_manager.py`) — production on Jetson. Applies `ConfigMap` +
   `Deployment` via the Kubernetes Python client.
2. **Docker** (`docker_manager.py`) — `production-local` mode and dev. Falls back
   automatically if `kubeconfig` is unavailable.

The backend is transparent to the rest of the agent.

## 3. Startup sequence

```
1. init_k8s_clients()  — try k3s; fall back to Docker
2. _wait_for_health("yolo",  YOLO_HEALTH_SOCK,  timeout=120s)
3. _wait_for_health("reid",  REID_HEALTH_SOCK,  timeout=120s)
4. _wait_for_health("iep1",  IEP1_HEALTH_SOCK,  timeout=60s)
5. _restore_active_cameras()  — re-add surviving cameras to IEP1 from ConfigMaps
6. _connect_to_eep()  — open bidirectional gRPC stream; exponential backoff reconnect
```

Restart recovery in step 5 reads `RTSP_URL` and `TARGET_FPS` from each camera's
ConfigMap (written by the agent when the camera was started), so an IEP1 restart
does not require EEP resync.

## 4. Per-camera lifecycle

**StartCamera** (from EEP):
1. Build ConfigMap data (`CAMERA_ID`, `STORE_ID`, `RTSP_URL`, `TARGET_FPS`,
   `WINDOW_SECONDS`, Redis URLs, DB URL, `CAMERA_CONFIG_ID`).
2. `apply_camera_configmap()` + `apply_iep2_deployment()` on the backend.
3. Wait for IEP2's gRPC health unix socket to report `SERVING` (timeout 60 s).
4. `AddCamera` RPC to IEP1 — IEP2 is now ready to consume from the Redis stream.
5. Spawn a per-camera `_watch_iep2_health` asyncio task.
6. Enqueue an immediate `CameraStatusReport` to EEP.

**StopCamera** (from EEP):
1. Cancel the per-camera health watcher task.
2. `RemoveCamera` RPC to IEP1.
3. `delete_iep2()` on the backend (Deployment + ConfigMap).
4. Enqueue an immediate `CameraStatusReport` to EEP.

Both handlers run as `asyncio.create_task` so k3s/Docker I/O never blocks the
EEP stream reader.

## 5. Health watching

- **Per-camera IEP2 watcher** — gRPC `Watch` on each camera's unix health socket.
  Sends an immediate status report on `NOT_SERVING` or stream failure.
- **IEP1 health watcher** — gRPC `Watch` on IEP1's health socket. On recovery
  (NOT_SERVING → SERVING), calls `_restore_active_cameras()` to re-add all
  cameras to the restarted IEP1.

## 6. EEP connection

- **Edge dials out** to EEP (avoids NAT); holds the stream open.
- Auth: shared secret in `x-agent-token` metadata on every RPC.
- TLS: loads CA cert from `GRPC_CA_CERT_PATH`; if file absent → insecure dev mode.
- Reconnect: exponential backoff 1 s → 60 s with jitter.
- Outgoing queue `maxsize=200`; full queue drops status reports with a warning
  (never blocks the event loop).

## 7. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `STORE_ID` | required | UUID of the store this device serves |
| `EEP_GRPC_URL` | required | `host:50051` |
| `AGENT_SECRET` | `""` | shared secret; empty = no auth (dev) |
| `GRPC_CA_CERT_PATH` | `/etc/retailvision/certs/ca.crt` | CA cert for TLS; missing = insecure |
| `IEP1_CONTROL_SOCK` | `unix:///dev/shm/sockets/iep1_control.sock` | gRPC AddCamera/RemoveCamera |
| `IEP1_HEALTH_SOCK` | `unix:///dev/shm/sockets/iep1_health.sock` | gRPC health Watch |
| `YOLO_HEALTH_SOCK` | `localhost:50052` | gRPC health of YOLO service |
| `REID_HEALTH_SOCK` | `localhost:50053` | gRPC health of ReID service |
| `LOCAL_REDIS_URL` | `redis://localhost:6379/0` | passed to IEP1 via ConfigMap |
| `SERVER_REDIS_URL` | `""` | passed to IEP2 via ConfigMap |
| `DATABASE_URL_SERVER` | `""` | passed to IEP2 via ConfigMap |
| `HEARTBEAT_INTERVAL_S` | `30` | heartbeat + camera status sweep interval |
| `IPC_SOCKETS_HOST_PATH` | `/dev/shm/sockets` | host-side path for IEP2 health sockets |

## 8. Deployment

- **Production:** installed as `retailvision-edge-agent.service` by
  `scripts/bootstrap-edge-k3s.sh`. Runs as systemd, restarts on failure.
- **Dev:** `docker compose --profile edge up edge_agent_dev` — uses Docker backend,
  requires a running Docker socket.
- **Logs:** `journalctl -u retailvision-edge-agent -f` (production) or
  `docker compose logs -f edge_agent_dev` (dev).
