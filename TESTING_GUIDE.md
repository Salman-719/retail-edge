# RetailVision — Backend Testing Guide

End-to-end verification of EEP, IEP1, and IEP2 from first boot through scheduler auto-fire.
All commands are PowerShell. JSON bodies use `ConvertTo-Json` — never inline raw strings.

---

## Prerequisites

- Docker Desktop running
- PowerShell 5.1+
- Python with `grpcio==1.64.0` installed (`pip install grpcio==1.64.0`) — for the gRPC test client only
- All commands run from `retail-edge/`

---

## Section 0 — Infrastructure

Start the shared services. Run this once before any group.

```powershell
docker compose up -d postgres redis minio
docker compose up -d --build eep
```

Verify EEP is healthy:
```powershell
docker compose logs eep | Select-String "gRPC server started|Scheduler started"
```
Expected: two lines — gRPC server started on port 50051, scheduler started.

---

## Section 1 — One-time Account & Store Setup

Run these steps once on a fresh database. They populate all IDs used throughout the
guide and set the variables that every subsequent command depends on.

> If EEP was restarted or you opened a new PowerShell session, skip to
> **Per-session: Restore Variables** to reload the IDs without recreating data.

### 1A — Register owner account

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/register" `
  -ContentType "application/json" `
  -Body (@{
      name     = "Test Owner"
      email    = "owner@retailvision.test"
      password = "testpass123"
  } | ConvertTo-Json)
```
Expected: `{ user_id, email, account_type: "owner" }`

### 1B — Login and capture token

```powershell
$resp  = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/login" `
  -ContentType "application/json" `
  -Body (@{
      email    = "owner@retailvision.test"
      password = "testpass123"
  } | ConvertTo-Json)
$TOKEN = $resp.access_token
```

### 1C — Create store

```powershell
$store    = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/stores" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      name    = "Test Store"
      slug    = "test-store"
      address = "123 Test Street"
  } | ConvertTo-Json)
$SLUG     = $store.slug
$STORE_ID = $store.store_id
```
Expected: `{ store_id: "<uuid>", slug: "test-store" }`

### 1D — Create draft version

```powershell
$draft      = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/versions/draft" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ clone_from_active = $false } | ConvertTo-Json)
$VERSION_ID = [string]$draft.id
```
Expected: `{ id, status: "draft", ... }`

### 1E — Get the default section (auto-created with the store)

```powershell
$sections   = Invoke-RestMethod -Method GET `
  -Uri "http://localhost:8000/api/store/$SLUG/sections" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
$SECTION_ID = [string]$sections[0].id
```
Expected: at least one section named "Main Floor".

### 1F — Create physical camera

```powershell
$camera    = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/cameras" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      name             = "Camera 1"
      mounting         = "ceiling"
      cloud_stream_url = "rtsp://host.docker.internal:8554/test"
  } | ConvertTo-Json)
$CAMERA_ID = [string]$camera.id
```
Expected: `{ id: "<uuid>", name: "Camera 1", ... }`

### 1G — Place camera config in draft

```powershell
$camConfig        = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/draft/sections/$SECTION_ID/camera-configs" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      physical_camera_id = $CAMERA_ID
      position_x         = 0.0
      position_y         = 0.0
      height_meters      = 3.0
      fov_deg            = 90.0
  } | ConvertTo-Json)
$CAMERA_CONFIG_ID = [string]$camConfig.id
```
Expected: `{ id: "<uuid>", status: "pending", ... }`

### 1H — Update .env with real UUIDs

Edit `retail-edge/.env` and set:
```
STORE_ID=<value of $STORE_ID>
CAMERA_ID=<value of $CAMERA_ID>
```

These are picked up by `docker compose` for the `iep1_ingestion` and `iep2_vision` services.

### 1I — Save all variables for future sessions

```powershell
# Print all IDs so you can paste them into future sessions
Write-Host "STORE_ID          = $STORE_ID"
Write-Host "CAMERA_ID         = $CAMERA_ID"
Write-Host "SLUG              = $SLUG"
Write-Host "SECTION_ID        = $SECTION_ID"
Write-Host "VERSION_ID        = $VERSION_ID"
Write-Host "CAMERA_CONFIG_ID  = $CAMERA_CONFIG_ID"
```

> **Note on draft activation**: Draft activation (uploading a floor plan image and running
> calibration) is not required for Groups A–F. The orchestrator's camera lookup does not
> filter by version status — the draft version is sufficient for all current tests.

---

## Per-session: Restore Variables

At the start of any new PowerShell session, paste these with your actual UUIDs:

```powershell
$STORE_ID         = "d313d5a2-5a89-4429-8c05-2effd871302b"
$CAMERA_ID        = "a0f46da1-bb1a-468d-853e-58f24c09fce9"
$SLUG             = "test-store"
$SECTION_ID       = "<your-section-id>"
$CAMERA_CONFIG_ID = "<your-camera-config-id>"

$resp  = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/login" `
  -ContentType "application/json" `
  -Body (@{ email = "owner@retailvision.test"; password = "testpass123" } | ConvertTo-Json)
$TOKEN = $resp.access_token
```

Container names derived from `$STORE_ID` and `$CAMERA_ID`:
- IEP1: `iep1_d313d5a2-5a89-4429-8c05-2effd871302b_a0f46da1-bb1a-468d-853e-58f24c09fce9`
- IEP2: `iep2_d313d5a2-5a89-4429-8c05-2effd871302b_a0f46da1-bb1a-468d-853e-58f24c09fce9`

---

## Group A — Proto Stubs

Requires EEP running.

**A1 — Generated files exist inside the EEP container**
```powershell
docker compose exec eep ls app/grpc_generated/
```
Expected: `__init__.py  agent_pb2.py  agent_pb2_grpc.py`

**A2 — No bare `import agent_pb2` in the stub**
```powershell
docker compose exec eep grep "^import agent_pb2" app/grpc_generated/agent_pb2_grpc.py
```
Expected: no output

**A3 — Package-qualified import is present**
```powershell
docker compose exec eep grep "grpc_generated import agent_pb2" app/grpc_generated/agent_pb2_grpc.py
```
Expected: exactly one line

**A4 — Messages importable and correct**
```powershell
docker compose exec eep python -c "
from app.grpc_generated import agent_pb2, agent_pb2_grpc
hb = agent_pb2.Heartbeat(store_id='s1', agent_version='0.1', timestamp_ms=1000)
print('store_id:', hb.store_id)
print('stub:', agent_pb2_grpc.AgentServiceStub)
"
```
Expected: `store_id: s1` and the stub class — no ImportError

**A5 — StartCamera carries all required fields**
```powershell
docker compose exec eep python -c "
from app.grpc_generated import agent_pb2
cmd = agent_pb2.StartCamera(
    camera_id='cam-01', store_id='store-01',
    rtsp_url='rtsp://cam/stream', target_fps=5.0, window_seconds=60.0,
    redis_url='redis://localhost:6379/0',
    s3_config=agent_pb2.S3Config(
        endpoint_url='http://minio:9000', access_key='rv',
        secret_key='rv_dev', bucket='retailvision'),
)
print('camera_id:', cmd.camera_id)
print('target_fps:', cmd.target_fps)
print('s3 bucket:', cmd.s3_config.bucket)
"
```
Expected: all three fields printed correctly

---

## Group B — EEP gRPC Server

**B1 — EEP starts with scheduler and gRPC server**
```powershell
docker compose up -d --build eep
docker compose logs eep | Select-String "gRPC server started|Scheduler started"
```
Expected: two log lines — one for gRPC on port 50051, one for scheduler

**B2 — Port 50051 is reachable**
```powershell
Test-NetConnection -ComputerName localhost -Port 50051
```
Expected: `TcpTestSucceeded : True`

**B3 — Reflection API lists the service**
```powershell
docker run --rm --network host fullstorydev/grpcurl -plaintext localhost:50051 list
```
Expected: `retailvision.agent.v1.AgentService` in output

**B4 — Heartbeat accepted; agent marked online**

grpcurl on Windows PowerShell has JSON quoting issues. Use the included Python test client
(run from `retail-edge/`):
```powershell
python test_grpc_heartbeat.py
```
Expected output:
```
[*] Connecting to localhost:50051
[*] store_id = d313d5a2-5a89-4429-8c05-2effd871302b
[*] Heartbeat sent — holding connection for 15s
[*] Check EEP logs and the edge_agents table now.
[*] Disconnecting.
```
EEP logs must show: `Agent connected`

**B5 — edge_agents row created; goes offline on disconnect**

While B4 is still running in another terminal:
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT store_id, status, last_heartbeat_at, agent_version FROM edge_agents;"
```
Expected: one row, `status=online`, `last_heartbeat_at` populated.

Then Ctrl+C the B4 process and wait 3 seconds:
```powershell
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

---

## Group C — Edge Agent

Prerequisite: `docker compose up -d eep postgres redis minio`

**C1 — Build and start the edge agent (dev profile)**
```powershell
docker compose --profile edge up -d --build edge_agent_dev
```
Expected: container starts and stays running

**C2 — EEP sees the agent connect**
```powershell
Start-Sleep 3
docker compose logs eep | Select-String "Agent connected"
```
Expected: `Agent connected store_id=d313d5a2-...`

**C3 — DB shows online**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT store_id, status, last_heartbeat_at FROM edge_agents;"
```
Expected: `status=online`

**C4 — Stop agent → offline**
```powershell
docker compose --profile edge stop edge_agent_dev
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

**C5 — Restart agent → back to online**
```powershell
docker compose --profile edge start edge_agent_dev
Start-Sleep 5
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=online`

---

## Group D — Debug Endpoint (IEP1 only, no auth required)

Prerequisites: EEP up, `edge_agent_dev` running and connected.

Build the IEP1 image once:
```powershell
docker build -t retailvision-iep1:latest .\services\iep1_ingestion
```

**D1 — Send StartCamera**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/debug/agent/command" `
  -ContentType "application/json" `
  -Body (@{
      store_id  = $STORE_ID
      camera_id = $CAMERA_ID
      action    = "start"
      rtsp_url  = "rtsp://host.docker.internal:8554/test"
  } | ConvertTo-Json)
```
Expected: `status: sent  action: start  camera_id: <uuid>`

**D2 — IEP1 container appears**
```powershell
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: container `iep1_$STORE_ID_$CAMERA_ID` is listed.
The container may exit quickly if the RTSP source is not live — acceptable. The container
appearing proves the gRPC wiring works end-to-end.

**D3 — Send StopCamera**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/debug/agent/command" `
  -ContentType "application/json" `
  -Body (@{
      store_id  = $STORE_ID
      camera_id = $CAMERA_ID
      action    = "stop"
  } | ConvertTo-Json)
```
Expected: `status: sent  action: stop`

**D4 — Container gone**
```powershell
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: empty output

---

## Group E — Schedule Trigger (IEP1 + IEP2 via orchestrator)

Prerequisites: everything from Group C + D, plus the IEP2 image built:
```powershell
docker build -t retailvision-iep2:latest .\services\iep2_vision
```

**E1 — Create a schedule**
```powershell
$schedule    = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      camera_config_id = $CAMERA_CONFIG_ID
      days_of_week     = @(0,1,2,3,4,5,6)
      start_time       = "00:00"
      end_time         = "23:59"
      is_active        = $true
  } | ConvertTo-Json -Depth 5)
$SCHEDULE_ID = [string]$schedule.id
```
Expected: 201 with the new schedule object

**E2 — Trigger start → IEP1 + IEP2 both start**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "start" } | ConvertTo-Json)
```
Expected: `status: accepted  action: start`

```powershell
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: both containers appear

**E3 — Trigger stop → both containers gone**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "stop" } | ConvertTo-Json)

docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: no iep1_ or iep2_ containers

---

## Group F — Scheduler Auto-fire

Prerequisites: everything from Group E.

**F1 — Create a schedule whose window opens within 2 minutes**
```powershell
$start = (Get-Date).ToUniversalTime().AddMinutes(2).ToString("HH:mm")

$SCHEDULE_ID = [string](Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      camera_config_id = $CAMERA_CONFIG_ID
      days_of_week     = @(0,1,2,3,4,5,6)
      start_time       = $start
      end_time         = "23:59"
      is_active        = $true
  } | ConvertTo-Json -Depth 5)).id
```
Expected: 201 with schedule created

**F2 — Wait for the scheduler to fire**

The scheduler evaluates every 60 seconds. Wait up to 3 minutes from the `start_time` set above.
```powershell
Start-Sleep 90
docker compose logs eep | Select-String "SCHEDULE|Camera workers started"
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: a `SCHEDULE: start camera` log line appears and the IEP2 container starts

**F3 — Confirm no duplicate start on the next cycle**

This verifies `_running_cameras` prevents the scheduler from double-starting the same camera.
```powershell
Start-Sleep 65
docker compose logs eep | Select-String "SCHEDULE: start camera"
```
Expected: no new `start camera` log line for this camera in this cycle — the scheduler
skips it because the key is already in `_running_cameras`

---

---

## Group G — End-to-End Pipeline Test

Validates the full chain: schedule trigger → IEP1 (frames to S3 + Redis) → IEP2 (YOLO +
ByteTrack + floor projection) → `tracking_history` rows in PostgreSQL. Nine pytest assertions
across four subsystems: DB, Redis consumer group, S3, and container lifecycle.

### Additional prerequisite: draft must be activated

Groups A–F work with a draft version. Group G requires an **active** version because IEP2's
floor projector only loads calibration when the version status is `active`.

Activate using the SQL bypass below (avoids the floor-plan image upload and full calibration
UI flow — appropriate for a test environment):

```powershell
docker compose exec postgres psql -U retailvision -d retailvision -c "
  INSERT INTO floor_plans (version_id, section_id, image_uploaded)
    VALUES ('$VERSION_ID', '$SECTION_ID', true);

  INSERT INTO calibrations (camera_config_id, method, status, is_current, homography_matrix)
    VALUES (
      '$CAMERA_CONFIG_ID',
      'homography',
      'verified',
      true,
      '[[1,0,0],[0,1,0],[0,0,1]]'
    );

  UPDATE camera_configs
    SET status = 'verified'
    WHERE id = '$CAMERA_CONFIG_ID';

  UPDATE store_config_versions
    SET status = 'active', active_from = NOW()
    WHERE id = '$VERSION_ID';
"
```

The identity homography (`[[1,0,0],[0,1,0],[0,0,1]]`) maps pixels 1:1 to floor meters —
sufficient to produce non-NULL `floor_x` / `floor_y` values in `tracking_history`.

### Additional prerequisite: live RTSP source

IEP1 reads from the RTSP URL stored on the physical camera (`cloud_stream_url`). In Section 1F
this was set to `rtsp://host.docker.internal:8554/test`. A MediaMTX server must be running
on the Windows host serving a test video on that path. The video must contain at least one
visible person — an empty scene produces zero YOLO detections and zero `tracking_history` rows,
making the test inconclusive.

### G1 — Build the test runner image (once)

```powershell
docker build -t retailvision-e2e:latest -f tests/Dockerfile .
```

The image installs only the test dependencies (`pytest`, `pytest-asyncio`, `asyncpg`,
`redis`, `boto3`). Test code is mounted at runtime so this only needs rebuilding when
`tests/e2e/requirements.txt` changes.

### G2 — Start the pipeline and let it run for 60 seconds

If not already running from Group E, trigger the pipeline start:

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "start" } | ConvertTo-Json)
```

Then wait one full batch window:

```powershell
Start-Sleep 60
```

After 60 seconds IEP1 will have uploaded at least one frame batch to S3 and published the
manifest to Redis. IEP2 will have consumed it and written rows to `tracking_history`.

### G3 — Run the e2e pytest suite

```powershell
docker run --rm `
  --network retail-edge_default `
  -v "${PWD}:/workspace" `
  -e DATABASE_URL="postgresql+asyncpg://retailvision:retailvision_dev@postgres:5432/retailvision" `
  -e REDIS_URL="redis://redis:6379/0" `
  -e S3_ENDPOINT_URL="http://minio:9000" `
  -e S3_ACCESS_KEY="retailvision" `
  -e S3_SECRET_KEY="retailvision_dev" `
  -e S3_BUCKET="retailvision" `
  -e E2E_CAMERA_ID="$CAMERA_ID" `
  -e E2E_STORE_ID="$STORE_ID" `
  retailvision-e2e:latest `
  pytest tests/e2e/test_full_pipeline.py -v
```

### G4 — Expected results

All 9 tests must pass:

| Test | What it checks |
|------|----------------|
| `test_rows_exist` | At least one row in `tracking_history` for this camera |
| `test_local_id_is_uuid` | `local_id` column is a proper UUID object |
| `test_store_id_matches` | Every row carries the correct `store_id` |
| `test_timestamp_ms_populated` | No NULL or zero `timestamp_ms` values |
| `test_floor_coords_populated` | At least some rows have non-NULL `floor_x` / `floor_y` |
| `test_bbox_area_positive` | `bbox_area > 0` for all rows |
| `test_bbox_confidence_range` | `bbox_confidence` in `[0.0, 1.0]` for all rows |
| `test_consumer_group_exists` | Redis stream `stream:iep1:{camera_id}` has group `iep2_workers` |
| `test_no_pending_messages` | All stream messages have been ACKed by IEP2 |

### G5 — Teardown

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "stop" } | ConvertTo-Json)

Start-Sleep 15
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: empty output — no running iep1_ or iep2_ containers.

Stop the edge agent:
```powershell
docker compose --profile edge stop edge_agent_dev
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

---

## Architecture Reference

| Component | Responsibility |
|-----------|----------------|
| `/api/debug/agent/command` | Auth-free; sends `StartCamera` gRPC → edge agent → IEP1 via Docker. IEP2 not involved. |
| `/store/{slug}/schedules/{id}/trigger` | Requires auth (owner or manager); calls `orchestrator.start_camera_workers()` → IEP1 via edge agent gRPC + IEP2 via EEP Docker socket. |
| `edge_agent_dev` compose service | Uses the `edge` profile — always include `--profile edge`. |
| IEP1 image | Must be tagged `retailvision-iep1:latest` (default in `edge_agent_dev` env). |
| IEP2 image | Must be tagged `retailvision-iep2:latest` (default in EEP's `IEP2_IMAGE` env). |
| `_running_cameras` | In-memory set in `camera_scheduler.py`; resets on EEP restart. Prevents scheduler double-starts. |
| Draft version | Does not need to be activated for Groups A–F. Group G requires activation for IEP2's floor projector to load calibration. |
| E2E test runner | Built from `tests/Dockerfile`; mounts project root at `/workspace`; connects to compose network `retail-edge_default`. |
