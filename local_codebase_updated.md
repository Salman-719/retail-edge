# RetailVision — Codebase Audit Report

**Date of audit:** 2026-06-03
**Repo label:** local
**Git branch:** `feature/new-iep1-2-3`
**Last commit:** `72a3a46 feat: synced vision debug console with store config`

---

## 0. Repo Identity

- **Repo name / label:** local
- **Git branch currently checked out:** `feature/new-iep1-2-3`
- **Last commit hash and message:** `72a3a46 feat: synced vision debug console with store config`
- **Date of audit:** 2026-06-03

---

## 1. Top-Level Directory Tree

```
c:/Users/jawad/Desktop/RetailVision_New
c:/Users/jawad/Desktop/RetailVision_New/retail-edge
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.claude
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.claude/settings.local.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.env
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.env.example
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.git
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.github
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.github/workflows
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.gitignore
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.pytest_cache
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.pytest_cache/.gitignore
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.pytest_cache/CACHEDIR.TAG
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.pytest_cache/README.md
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/.pytest_cache/v
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/C:tempopenapi.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/README.md
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/RetailVision-Phase1.postman_collection.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/RetailVision-Phase2-3.postman_collection.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/RetailVision-Phase4.postman_collection.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/RetailVision-Validation-Tests.postman_collection.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/TESTING_GUIDE.md
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/codebase_audit.md
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/docker-compose.yml
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/.env
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/.env.example
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/Dockerfile
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/dist
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/index.html
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/nginx.conf
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/node_modules
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/package-lock.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/package.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/postcss.config.js
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/src
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/tailwind.config.js
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/frontend/vite.config.js
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/infra
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/infra/.gitkeep
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/openapi.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/package-lock.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/prompts
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/prompts/.gitkeep
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/pyproject.toml
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/request.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/__init__.py
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/__pycache__
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/edge_agent
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/eep
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep1_ingestion
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep2_vision
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep3_reconciliation
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep4_alerts
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep5_analytics
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/iep6_agent
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/services/live_bridge
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/stream.json
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/test_grpc_heartbeat.py
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/testing-data
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/testing-data/Test1
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/testing-data/Test2
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/testing-data/Test3
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests/Dockerfile
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests/__init__.py
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests/__pycache__
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests/e2e
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/tests/unit
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/utputFormat
c:/Users/jawad/Desktop/RetailVision_New/retail-edge/yolov8n.pt
```

---

## 2. Service Root Paths

- **EEP:** `services/eep/`
- **IEP1:** `services/iep1_ingestion/`
- **IEP2:** `services/iep2_vision/`
- **Edge Agent:** `services/edge_agent/`
- **Shared / common package:** NOT PRESENT

---

## 3. EEP — File Inventory & Key Details

### 3.1 File list

```
services/eep/app/__init__.py
services/eep/app/api/__init__.py
services/eep/app/api/routers/__init__.py
services/eep/app/api/routers/audit.py
services/eep/app/api/routers/auth.py
services/eep/app/api/routers/config.py
services/eep/app/api/routers/debug.py
services/eep/app/api/routers/draft.py
services/eep/app/api/routers/employees.py
services/eep/app/api/routers/members.py
services/eep/app/api/routers/schedules.py
services/eep/app/api/routers/settings.py
services/eep/app/api/routers/shifts.py
services/eep/app/api/routers/stores.py
services/eep/app/core/audit.py
services/eep/app/core/auth.py
services/eep/app/core/config.py
services/eep/app/core/database.py
services/eep/app/core/email.py
services/eep/app/core/iep2_docker.py
services/eep/app/core/orchestrator.py
services/eep/app/core/redis_client.py
services/eep/app/core/s3_client.py
services/eep/app/core/scheduler.py
services/eep/app/grpc_generated/__init__.py
services/eep/app/grpc_generated/agent_pb2.py
services/eep/app/grpc_generated/agent_pb2_grpc.py
services/eep/app/grpc_server/__init__.py
services/eep/app/grpc_server/camera_status.py
services/eep/app/grpc_server/registry.py
services/eep/app/grpc_server/server.py
services/eep/app/grpc_server/servicer.py
services/eep/app/main.py
services/eep/app/middleware/__init__.py
services/eep/app/middleware/store_auth.py
services/eep/app/models/__init__.py
services/eep/app/models/alert_config.py
services/eep/app/models/audit_log.py
services/eep/app/models/base.py
services/eep/app/models/calibration.py
services/eep/app/models/camera_config.py
services/eep/app/models/camera_runtime_session.py
services/eep/app/models/camera_schedule.py
services/eep/app/models/coordinate_frame.py
services/eep/app/models/edge_agent.py
services/eep/app/models/employee.py
services/eep/app/models/floor_plan.py
services/eep/app/models/invitation.py
services/eep/app/models/obstacle.py
services/eep/app/models/password_reset_token.py
services/eep/app/models/physical_camera.py
services/eep/app/models/refresh_token.py
services/eep/app/models/section.py
services/eep/app/models/shift_instance.py
services/eep/app/models/shift_pattern.py
services/eep/app/models/store.py
services/eep/app/models/store_member.py
services/eep/app/models/store_settings.py
services/eep/app/models/user.py
services/eep/app/models/version.py
services/eep/app/models/version_sync_event.py
services/eep/app/models/zone.py
services/eep/app/schemas/__init__.py
services/eep/app/schemas/auth.py
services/eep/app/schemas/camera_schedule.py
services/eep/app/schemas/config.py
services/eep/app/schemas/draft.py
services/eep/app/schemas/employees.py
services/eep/app/schemas/member.py
services/eep/app/schemas/shifts.py
services/eep/app/schemas/store.py
services/eep/app/tasks/__init__.py
services/eep/app/tasks/camera_scheduler.py
services/eep/app/utils/__init__.py
services/eep/app/utils/calibration_xml.py
services/eep/app/utils/homography.py
services/eep/app/utils/shapely_utils.py
services/eep/proto/agent.proto
services/eep/requirements.txt
services/eep/schema.sql
services/eep/test_heartbeat.py
```

### 3.2 Schema ownership

- **File that defines the PostgreSQL schema:** `services/eep/schema.sql`
- **Does EEP call `create_all` or run a `.sql` file at startup?**
  - Both. At startup (`services/eep/app/main.py` lines 119–120), EEP calls `ModelBase.metadata.create_all` via SQLAlchemy ORM inside the `lifespan` context manager. The `schema.sql` file is also mounted into the PostgreSQL container via docker-compose as `docker-entrypoint-initdb.d/schema.sql` (runs once on first container init, not by EEP directly).
  - Additionally, `main.py` line 114 runs a raw `ALTER TABLE` to add `deactivated_at` column if absent.
- **Does any service other than EEP create tables?**
  - NO. `services/iep2_vision/persistence/postgres.py` explicitly says "No DDL — pure async DB I/O." IEP1, IEP2, and Edge Agent contain no `CREATE TABLE` calls.

### 3.3 gRPC

- **Proto file path:** `services/eep/proto/agent.proto`
- **Generated stubs path:** `services/eep/app/grpc_generated/` (`agent_pb2.py`, `agent_pb2_grpc.py`)
- **gRPC server class:** `AgentServiceServicer` in `services/eep/app/grpc_server/servicer.py`; **port:** `50051`
- **Does EEP use `grpc.aio` or sync `grpc`?** `grpc.aio` — `services/eep/app/grpc_server/server.py` line 12: `_server: grpc.aio.Server | None = None`; server created with `grpc.aio.server()`

### 3.4 IEP2 lifecycle management

- **File and function that starts IEP2 containers:** `services/eep/app/core/iep2_docker.py` — function `start_iep2()`
- **File and function that stops IEP2 containers:** `services/eep/app/core/iep2_docker.py` — function `stop_iep2()`
- **Does it call Docker socket directly?** Yes — `services/eep/app/core/iep2_docker.py` uses `docker.from_env()` which connects to the Docker socket. The Docker socket is mounted into the EEP container via `docker-compose.yml` line 109: `/var/run/docker.sock:/var/run/docker.sock`.
- **Does it call Kubernetes API?** No

### 3.5 Camera scheduler

- **File path:** `services/eep/app/tasks/camera_scheduler.py`
- **Library used:** APScheduler (`apscheduler.schedulers.asyncio.AsyncIOScheduler`) — `services/eep/app/core/scheduler.py`
- **Scheduler tick interval:** 60 seconds — `services/eep/app/core/scheduler.py` line 14: `seconds=60`
- **What action does a tick trigger?** Calls `evaluate_schedules()` in `camera_scheduler.py`. This loads all active `camera_schedules` rows from DB, evaluates each against the current local time in the store's timezone, and calls `_on_camera_start(row)` or `_on_camera_stop(row)` when the running state changes. It also calls `_activate_pending_versions()` to fire any `pending_activation` versions whose `activate_at` timestamp has passed.

### 3.6 Key dependencies (from `services/eep/requirements.txt`)

| Package | Version |
|---|---|
| `fastapi` | `0.115.0` |
| `uvicorn` | `0.30.1` |
| `sqlalchemy` | `2.0.30` |
| `asyncpg` | `0.29.0` |
| `redis` | `5.0.4` |
| `boto3` | `1.34.69` |
| `grpcio` | `1.64.0` |
| `grpcio-tools` | `1.64.0` |
| `docker` | `7.1.0` |
| `pydantic-settings` | `2.2.1` |
| `apscheduler` | `3.10.4` |

---

## 4. IEP1 — File Inventory & Key Details

### 4.1 File list

```
services/iep1_ingestion/app/main.py
services/iep1_ingestion/app/publisher.py
services/iep1_ingestion/app/runtime.py
services/iep1_ingestion/app/source/__init__.py
services/iep1_ingestion/app/source/base.py
services/iep1_ingestion/app/source/rtsp_source.py
services/iep1_ingestion/app/source/video_source.py
services/iep1_ingestion/app/uploader.py
services/iep1_ingestion/app/window.py
services/iep1_ingestion/requirements.txt
```

### 4.2 Entry point

- **CLI entry file path:** `services/iep1_ingestion/app/main.py`
- **CLI args accepted (exact argparse definition):**

```python
parser = argparse.ArgumentParser(
    prog="python -m services.iep1_ingestion.app.main",
    description="IEP1 ingestion worker — one process per camera",
)
parser.add_argument("--store-id",  required=True,                help="Store identifier")
parser.add_argument("--camera-id", required=True,                help="Camera identifier")
parser.add_argument("--rtsp",      required=False, default=None, help="RTSP stream URL")
parser.add_argument("--video",     default=None,
                    help="Path to a video file. Used instead of --rtsp for dev/test.")
parser.add_argument("--fps",       type=float, default=5.0,      help="Target FPS (default: 5.0)")
parser.add_argument("--window",    type=float, default=60.0,     help="Batch window seconds (default: 60.0)")
```

### 4.3 Frame source

- **Class that reads frames from RTSP:** `RtspSource` in `services/iep1_ingestion/app/source/rtsp_source.py`
- **Class that reads frames from video file:** `VideoFileSource` in `services/iep1_ingestion/app/source/video_source.py`
- **`FrameSource` protocol/base class:** Yes — `services/iep1_ingestion/app/source/base.py`, `FrameSource` protocol with methods `frames()`, `is_available()`, `release()`
- **Is VideoFileSource implemented?** Yes
- **Is RtspSource implemented?** Yes

### 4.4 S3 upload

- **File path of S3 uploader class:** `services/iep1_ingestion/app/uploader.py` — class `S3Uploader`
- **S3 key format used (exact string pattern):**
  ```python
  S3_KEY_PREFIX = "frames"
  key = f"{S3_KEY_PREFIX}/{self.camera_id}/{capture_ts_ms}.jpg"
  ```
  Expands to: `frames/{camera_id}/{capture_ts_ms}.jpg`
- **JPEG quality value:** `JPEG_QUALITY = 85` (`uploader.py` line 13)
- **Upload retry count:** `UPLOAD_RETRY_ATTEMPTS = 3` (`uploader.py` line 14)

### 4.5 Window / batch logic

- **File path of window accumulator:** `services/iep1_ingestion/app/window.py` — class `WindowAccumulator`
- **Window size default (seconds):** `60.0` (set via `--window` arg in main.py, default `60.0`)
- **Gap detection threshold (exact condition):**
  ```python
  GAP_MULTIPLIER = 1.5
  if (capture_ts_ms - prev_ts) > GAP_MULTIPLIER * self._sample_interval_ms:
      self._gaps.append(Gap(start_ts_ms=prev_ts, end_ts_ms=capture_ts_ms))
  ```
  A gap is recorded when the inter-frame interval exceeds `1.5 × (1000 / sample_fps)` milliseconds.
- **Status classification rules:**
  ```python
  ONLINE_FRAME_RATIO  = 0.8
  OFFLINE_FRAME_RATIO = 0.2

  if ratio >= ONLINE_FRAME_RATIO:   status = "online"
  elif ratio <= OFFLINE_FRAME_RATIO: status = "offline"
  else:                              status = "degraded"
  ```
  where `ratio = frame_count / expected_frames`
- **Fields in WindowManifest:**
  ```python
  @dataclass
  class WindowManifest:
      window_start_ms:  int
      window_end_ms:    int
      batch_number:     int
      status:           str
      frames:           List[Tuple[int, str]]
      gaps:             List[Gap]
      frame_count:      int
      expected_frames:  int
  ```

### 4.6 Redis publish

- **File path of publisher:** `services/iep1_ingestion/app/publisher.py` — class `WindowPublisher`
- **Redis stream name pattern (exact):**
  ```python
  STREAM_PREFIX = "stream:iep1"
  def _stream_name(self) -> str:
      return f"{STREAM_PREFIX}:{self.camera_id}"
  ```
  Expands to: `stream:iep1:{camera_id}`
- **Redis command used:** `XADD` — `publisher.py` line 34: `self._client.xadd(self._stream_name(), {"manifest": self._serialize(manifest)})`
- **Is there a buffer for Redis downtime?** Yes. `BUFFER_MAX_SIZE = 64`. Uses `collections.deque(maxlen=BUFFER_MAX_SIZE)`. On Redis failure, manifests are appended to the buffer. On reconnect, the buffer is drained (oldest-first) before the current manifest is published.

### 4.7 S3 cleanup / TTL

- **Where and when are old S3 keys deleted:** `services/iep1_ingestion/app/runtime.py` — `Iep1Runtime._flush_expired_batches()` called on every frame iteration and after each window close. On process exit (finally block), all remaining pending batches are unconditionally deleted.
- **TTL value in seconds:** `BATCH_TTL_SECONDS = 300` (`runtime.py` line 13; i.e. 5 minutes)

### 4.8 Key dependencies (from `services/iep1_ingestion/requirements.txt`)

| Package | Version |
|---|---|
| `opencv-python-headless` | `4.9.0.80` |
| `boto3` | `1.34.0` |
| `redis` | `5.0.1` |
| `numpy` | `1.26.4` |

---

## 5. IEP2 — File Inventory & Key Details

### 5.1 File list

```
services/iep2_vision/__init__.py
services/iep2_vision/app/__init__.py
services/iep2_vision/app/main.py
services/iep2_vision/detector/__init__.py
services/iep2_vision/detector/detector.py
services/iep2_vision/identity/__init__.py
services/iep2_vision/identity/gallery.py
services/iep2_vision/identity/manager.py
services/iep2_vision/identity/pools.py
services/iep2_vision/identity/spatial_gate.py
services/iep2_vision/ingest/__init__.py
services/iep2_vision/ingest/redis_source.py
services/iep2_vision/live_publisher.py
services/iep2_vision/main.py
services/iep2_vision/persistence/__init__.py
services/iep2_vision/persistence/postgres.py
services/iep2_vision/projection/__init__.py
services/iep2_vision/projection/projector.py
services/iep2_vision/reid/__init__.py
services/iep2_vision/reid/reid.py
services/iep2_vision/requirements.txt
services/iep2_vision/runtime.py
services/iep2_vision/tracker/__init__.py
services/iep2_vision/tracker/tracker.py
services/iep2_vision/video_ingestor/__init__.py
services/iep2_vision/video_ingestor/ingestor.py
```

### 5.2 Entry point

- **CLI entry file path:** `services/iep2_vision/main.py`
- **CLI args accepted (exact argparse definition):**

```python
parser = argparse.ArgumentParser(
    description="IEP2 vision worker — one process per camera",
)
parser.add_argument("--store-id",          required=True,  type=_uuid_arg, help="Store identifier (UUID)")
parser.add_argument("--camera-id",         required=True,                  help="Camera identifier")
parser.add_argument("--camera-config-id",  default=None,   type=_uuid_arg,
                    help="UUID of the camera_configs row. Required for floor projection. "
                         "If omitted, floor_x/floor_y/zone_id are stored as NULL.")
parser.add_argument("--source",            choices=["video", "redis"],
                    default="video",                                        help="Frame source: video (default) or redis")
parser.add_argument("--video",             default=None,                   help="Path to video file (required when --source video)")
parser.add_argument("--start-ms",          type=int, default=0,            help="Start timestamp offset ms (default: 0)")
```

- **Run modes supported:** `video` (reads from a video file), `redis` (reads IEP1 manifests from Redis stream + fetches frames from S3)

### 5.3 Ingest sources

- **File path of Redis ingest source:** `services/iep2_vision/ingest/redis_source.py` — class `RedisStreamFrameSource`
- **Redis command used:** `XREADGROUP`
- **Consumer group name:** `iep2_workers` (constant `GROUP_NAME = "iep2_workers"` in `redis_source.py` line 17)
- **Does it ACK messages?** Yes. `redis_source.py` line 113: `await self._redis.xack(self._stream_name, GROUP_NAME, message_id)`. ACK is called by the caller (`runtime.py`) after all frames in the manifest are processed and written to DB.
- **File path of video file ingest source:** `services/iep2_vision/video_ingestor/ingestor.py` — function `extract_frames()`; wrapped in `runtime.py` `_video_source()` static method

### 5.4 Vision pipeline

- **Detector:** model name `yolov8n.pt`, library `ultralytics` (via `ultralytics.YOLO`), file `services/iep2_vision/detector/detector.py`
- **Tracker:** algorithm ByteTrack, library `supervision` (`sv.ByteTrack`), file `services/iep2_vision/tracker/tracker.py`
- **ReID:** model name `osnet_x1_0`, library `boxmot` (`boxmot.reid.core.reid.ReID`), file `services/iep2_vision/reid/reid.py`
- **Are models loaded once at init or per frame?** Once at init — `IEP2Runtime.__init__()` in `runtime.py` lines 143–148: `self.yolo_model = _load_yolo()` and `self.reid_model = _load_reid()` are called once at construction time.

### 5.5 Identity management

- **File path of LocalIdentityManager:** `services/iep2_vision/identity/manager.py` — class `LocalIdentityManager`
- **Does a Lost pool exist?** Yes — `self._lost: dict[int, LostEntry]` (keyed by `local_id`)
- **Three-pool structure:** Yes — Active / Pending / Lost:
  - `self._active: dict[int, ActiveTrack]` — confirmed tracks with assigned `local_id`
  - `self._pending: dict[int, PendingTrack]` — new tracks collecting init embeddings before ReID
  - `self._lost: dict[int, LostEntry]` — disappeared active tracks, held for TTL=150 frames (30 s @ 5 fps)
- **ReID matching cosine similarity threshold:** Base threshold `0.75` — `identity/spatial_gate.py` line 18: `base_threshold: float = 0.75`. Dynamic adjustment via `SpatialGateConfig`: `adjusted = base_threshold + (d_ratio * 0.2) - (t_ratio * 0.15)`, clamped to `[0.35, 1.0]`.

### 5.6 Floor projection

- **Is homography / floor projection implemented?** Yes
- **File path:** `services/iep2_vision/projection/projector.py` — class `FloorProjector`
- **Where is homography matrix loaded from?** PostgreSQL `calibrations` table, queried at startup via `FloorProjector.load(pool, camera_config_id)`. SQL in `projector.py` lines 22–29 (`_HOMOGRAPHY_SQL`): selects `homography_matrix` from `calibrations` where `camera_config_id = $1` AND `is_current = true` AND `status IN ('ok', 'verified')` AND `method = 'homography'`.

### 5.7 Persistence

- **File path of persistence layer:** `services/iep2_vision/persistence/postgres.py` — class `PostgresPersistence`
- **Database driver used:** `asyncpg`
- **Is `tracking_history` write async or sync?** Async — `persistence/postgres.py` line 59: `await self._pool.execute(_INSERT_SQL, ...)`
- **Does IEP2 call `CREATE TABLE` itself?** No. Module docstring: "No identity logic, no embedding logic, no DDL — pure async DB I/O."
- **Exact columns written to `tracking_history`:**
  ```
  store_id, camera_id, local_id, timestamp_ms,
  floor_x, floor_y, zone_id,
  bbox_confidence, bbox_area
  ```
  (`id` and `created_at` are auto-populated by PostgreSQL defaults)

### 5.8 Batch / window model

- **Does IEP2 group frames into batches internally?** No. IEP2 processes individual frames as they arrive from the Redis stream. Batching is IEP1's concern; IEP2 consumes `WindowManifest` messages and iterates over their `frames` list frame-by-frame.
- **Does IEP2 emit a `batch_complete` event?** No.

### 5.9 Config

- **Config dataclass name and file path:** `Iep2Settings` dataclass in `services/iep2_vision/runtime.py` lines 54–66
- **How does IEP2 receive homography / calibration?** Via DB query at startup. `main.py` accepts `--camera-config-id` CLI arg (UUID). At runtime start, `FloorProjector.load(pool, camera_config_id)` queries the `calibrations` table via the asyncpg pool. No CLI arg or env var carries the homography matrix directly.

### 5.10 FastAPI adapter

- **Does a FastAPI wrapper exist in this service?** Yes
- **File path:** `services/iep2_vision/app/main.py`
- **Endpoints it exposes:**
  - `POST /upload` — accepts a video file upload + `physical_camera_id` + `store_id` form fields, runs the full vision pipeline in a background thread
  - `GET /ws` (WebSocket) — streams per-frame results as JSON to connected clients
  - `GET /frames` — returns all processed frames and pipeline status
  - `POST /stop` — signals the running pipeline to stop after the current frame
  - `POST /clear-tmp` — deletes all uploaded video files from the tmp directory
  - `GET /` — serves `ui/index.html` (static UI)

### 5.11 Key dependencies (from `services/iep2_vision/requirements.txt`)

| Package | Version |
|---|---|
| `ultralytics` | unpinned |
| `supervision` | `0.22.0` |
| `boxmot` | `>=10.0.0` (lower-bound only) |
| `asyncpg` | `0.29.0` |
| `psycopg2-binary` | NOT PRESENT |
| `redis` | `5.0.1` |
| `boto3` | `1.34.0` |
| `shapely` | `2.0.4` |
| `opencv-python-headless` | unpinned |
| `numpy` | NOT PRESENT (pulled in transitively) |
| `fastapi` | unpinned |

---

## 6. Edge Agent — File Inventory & Key Details

### 6.1 File list

```
services/edge_agent/app/__init__.py
services/edge_agent/app/agent.py
services/edge_agent/app/docker_manager.py
services/edge_agent/app/grpc_generated/__init__.py
services/edge_agent/app/grpc_generated/agent_pb2.py
services/edge_agent/app/grpc_generated/agent_pb2_grpc.py
services/edge_agent/app/main.py
services/edge_agent/proto/agent.proto
services/edge_agent/requirements.txt
```

### 6.2 gRPC client

- **Does it use `grpc.aio` or sync `grpc`?** `grpc.aio` — `agent.py` line 49: `async with grpc.aio.insecure_channel(grpc_url) as channel:`
- **Reconnect logic:** Yes. `agent.py` `run_agent()` function (lines 32–45): exponential backoff reconnect loop starting at `backoff=1` s, doubling on each failure up to `60` s. The `_outgoing` queue and `_tracked_cameras` dict are module-level and survive reconnects.

### 6.3 Docker management

- **File path of Docker manager:** `services/edge_agent/app/docker_manager.py`
- **How does it name IEP1 containers (exact naming convention):**
  ```python
  def container_name(store_id: str, camera_id: str) -> str:
      return f"iep1_{store_id}_{camera_id}"
  ```
- **Does it call the Docker socket directly via `docker` SDK?** Yes — `docker_manager.py` line 11: `_client = docker.from_env()`

### 6.4 Key dependencies (from `services/edge_agent/requirements.txt`)

| Package | Version |
|---|---|
| `grpcio` | `1.64.0` |
| `grpcio-tools` | `1.64.0` |
| `docker` | `7.1.0` |

---

## 7. Shared / Common Package (if present)

NOT PRESENT. There is no shared/common package directory. All services are self-contained. The repo root has a `services/__init__.py` (empty) that makes `services` importable as a Python namespace, but it exposes no shared logic.

### 7.1 File list
NOT PRESENT

### 7.2 What does it expose?
NOT PRESENT

### 7.3 Is it imported by IEP1? IEP2? EEP? Edge Agent?
NOT PRESENT — no shared package exists to import.

---

## 8. Docker Compose

### 8.1 Services declared

| Service | Image / Build context |
|---|---|
| `postgres` | `postgres:15-alpine` |
| `redis` | `redis:7-alpine` |
| `minio` | `minio/minio:latest` |
| `prometheus` | `prom/prometheus:v2.51.0` |
| `grafana` | `grafana/grafana:10.4.1` |
| `frontend` | build: `./frontend` |
| `eep` | build: `./services/eep` |
| `iep1_ingestion` | build: `./services/iep1_ingestion` |
| `iep2_vision` | build: `./services/iep2_vision` |
| `iep3_reconciliation` | build: `./services/iep3_reconciliation` |
| `iep4_alerts` | build: `./services/iep4_alerts` |
| `iep5_analytics` | build: `./services/iep5_analytics` |
| `iep6_agent` | build: `./services/iep6_agent` |
| `live_bridge` | build: `./services/live_bridge` |
| `iep2_dev` | build: `./services/iep2_vision` (profile: `dev`) |
| `edge_agent_dev` | build: `./services/edge_agent` (profile: `edge`) |

### 8.2 IEP1 container definition

```yaml
iep1_ingestion:
  build:
    context: ./services/iep1_ingestion
    dockerfile: Dockerfile
  environment:
    S3_ENDPOINT_URL: http://minio:9000
    S3_ACCESS_KEY: ${S3_ACCESS_KEY:-retailvision}
    S3_SECRET_KEY: ${S3_SECRET_KEY:-retailvision_dev}
    S3_BUCKET: ${S3_BUCKET:-retailvision}
    REDIS_URL: redis://redis:6379/0
  command: >
    python -m services.iep1_ingestion.app.main
    --store-id ${STORE_ID}
    --camera-id ${CAMERA_ID}
    --rtsp ${RTSP_URL}
    --fps ${TARGET_FPS:-5.0}
    --window ${BATCH_WINDOW_SECONDS:-60.0}
  depends_on:
    redis:
      condition: service_healthy
    minio:
      condition: service_healthy
```

### 8.3 IEP2 container definition

```yaml
iep2_vision:
  build:
    context: ./services/iep2_vision
    dockerfile: Dockerfile
  environment:
    DATABASE_URL: postgresql://${POSTGRES_USER:-retailvision}:${POSTGRES_PASSWORD:-retailvision_dev}@postgres:5432/${POSTGRES_DB:-retailvision}
    REDIS_URL: redis://redis:6379/0
    S3_ENDPOINT_URL: http://minio:9000
    S3_ACCESS_KEY: ${S3_ACCESS_KEY:-retailvision}
    S3_SECRET_KEY: ${S3_SECRET_KEY:-retailvision_dev}
    S3_BUCKET: ${S3_BUCKET:-retailvision}
    LIVE_STREAM_ENABLED: "true"
  volumes:
    - ./testing-data:/workspace/testing-data:ro
  command: >
    python services/iep2_vision/main.py
    --store-id ${STORE_ID}
    --camera-id ${CAMERA_ID}
    --source redis
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
    minio:
      condition: service_healthy
```

### 8.4 Edge Agent container definition

```yaml
edge_agent_dev:
  build:
    context: ./services/edge_agent
    dockerfile: Dockerfile
  environment:
    EEP_GRPC_URL: eep:50051
    STORE_ID: ${STORE_ID:-00000000-0000-0000-0000-000000000001}
    AGENT_VERSION: ${AGENT_VERSION:-0.1.0}
    IEP1_IMAGE: ${IEP1_IMAGE:-retailvision-iep1:latest}
    DOCKER_NETWORK: ${DOCKER_NETWORK:-retail-edge_default}
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  depends_on:
    - eep
  profiles:
    - edge
```

Note: The edge agent is only present as `edge_agent_dev` under the `edge` profile. There is no unconditional `edge_agent` service in docker-compose.yml.

### 8.5 Infra services

| Service | Image |
|---|---|
| `postgres` | `postgres:15-alpine` |
| `redis` | `redis:7-alpine` |
| `minio` (S3) | `minio/minio:latest` |

---

## 9. Data Contracts — Exact Values

### 9.1 Redis stream names

| Stream name | Written by | Read by |
|---|---|---|
| `stream:iep1:{camera_id}` | `services/iep1_ingestion/app/publisher.py` (`WindowPublisher._xadd()`) via `XADD` | `services/iep2_vision/ingest/redis_source.py` (`RedisStreamFrameSource.manifests()`) via `XREADGROUP` |

### 9.2 S3 key format

Exact string from `services/iep1_ingestion/app/uploader.py` lines 13 and 46:

```python
S3_KEY_PREFIX = "frames"
key = f"{S3_KEY_PREFIX}/{self.camera_id}/{capture_ts_ms}.jpg"
```

Expands to: `frames/{camera_id}/{capture_ts_ms}.jpg`

### 9.3 tracking_history table columns

From `services/eep/schema.sql` lines 692–704:

```sql
CREATE TABLE IF NOT EXISTS tracking_history (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id         UUID        NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_id        TEXT        NOT NULL,
    local_id         UUID        NOT NULL,
    timestamp_ms     BIGINT      NOT NULL,
    floor_x          DOUBLE PRECISION,
    floor_y          DOUBLE PRECISION,
    zone_id          UUID        REFERENCES zones(id) ON DELETE SET NULL,
    bbox_confidence  REAL        NOT NULL,
    bbox_area        INTEGER     NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 9.4 WindowManifest fields

From `services/iep1_ingestion/app/window.py` lines 19–28:

```python
@dataclass
class WindowManifest:
    window_start_ms:  int
    window_end_ms:    int
    batch_number:     int
    status:           str
    frames:           List[Tuple[int, str]]
    gaps:             List[Gap]
    frame_count:      int
    expected_frames:  int
```

---

## 10. Known Deviations & Self-Reported Gaps

Search results for `TODO`, `FIXME`, `HACK`, `deferred`, `not yet`, `placeholder` in `services/**/*.py`:

### `services/iep2_vision/identity/gallery.py`

```
line 4:   init    — placeholder embeddings collected on track birth, centroid via EMA
```

This is docstring documentation for the init-phase behavior of `EmbeddingGallery`, not an unfulfilled work item. The word "placeholder" describes the role of init-phase embeddings (temporary, replaced when sampled-phase embeddings arrive).

No `TODO`, `FIXME`, `HACK`, `deferred`, or `not yet` occurrences were found anywhere in the `services/` directory.

---

## 11. Tests

### 11.1 Test directory structure

```
tests/__init__.py
tests/e2e/__init__.py
tests/e2e/test_full_pipeline.py
tests/unit/__init__.py
```

Note: `tests/unit/` directory exists but contains only `__init__.py` — no unit test files.

### 11.2 What is tested?

| File | What it tests |
|---|---|
| `tests/e2e/test_full_pipeline.py` | End-to-end integration tests against a live running stack. Covers: `tracking_history` rows exist, `local_id` is UUID type, `store_id` matches, `timestamp_ms` is populated and non-zero, `floor_x`/`floor_y` populated, `bbox_area` positive, `bbox_confidence` in `[0, 1]`, Redis consumer group `iep2_workers` exists, no pending unACKed messages in stream, S3 frames uploaded under `frames/{camera_id}/` prefix. |

### 11.3 Test command

```
pytest tests/e2e/test_full_pipeline.py -v
```

Or to run all tests (per `pyproject.toml` `testpaths = ["tests"]`):

```
pytest
```

Prerequisites for e2e tests: full stack running (postgres, redis, minio, eep), edge agent connected, IEP1/IEP2 images built, env vars `DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `E2E_CAMERA_ID`, `E2E_STORE_ID` set.
