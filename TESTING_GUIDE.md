# RetailVision — Backend Testing Guide

End-to-end verification from database schema through the full pipeline.
All commands are PowerShell. JSON bodies use `ConvertTo-Json` — never inline raw strings.
Service checks use `Select-String` — never bare `grep`.

---

## Prerequisites

- Docker Desktop running
- PowerShell 5.1+
- Python with `grpcio==1.64.0` installed (`pip install grpcio==1.64.0`) — for the gRPC test client only
- All commands run from `retail-edge/`

---

## Section 0 — Infrastructure

Start the shared services once before any group.

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

Run these once on a fresh database. They populate all IDs used throughout the guide.

> Already have a database? Skip to **Per-session: Restore Variables**.

### 1A — Register owner account

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/register" `
  -ContentType "application/json" `
  -Body (@{
      name     = "Test Owner"
      email    = "owner1@retailvision.com"
      password = "testpass123"
  } | ConvertTo-Json)
```
Expected: `{ user_id, email, account_type: "owner" }`

### 1B — Login and capture token

```powershell
$resp  = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/login" `
  -ContentType "application/json" `
  -Body (@{ email = "owner1@retailvision.com"; password = "testpass123" } | ConvertTo-Json)
$TOKEN = $resp.access_token
```

### 1C — Create store

```powershell
$store    = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/stores" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ name = "Test Store"; slug = "test-store"; address = "123 Test Street" } | ConvertTo-Json)
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

### 1E — Get default section

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

### 1I — Print all variables for future sessions

```powershell
Write-Host "STORE_ID          = $STORE_ID"
Write-Host "CAMERA_ID         = $CAMERA_ID"
Write-Host "SLUG              = $SLUG"
Write-Host "SECTION_ID        = $SECTION_ID"
Write-Host "VERSION_ID        = $VERSION_ID"
Write-Host "CAMERA_CONFIG_ID  = $CAMERA_CONFIG_ID"
```

> **Draft activation**: Not required for Groups A–M. Group N (e2e) requires activation;
> instructions are in that section.

---

## Per-session: Restore Variables

```powershell
$STORE_ID         = "<your-store-id>"
$CAMERA_ID        = "<your-camera-id>"
$SLUG             = "test-store"
$SECTION_ID       = "<your-section-id>"
$VERSION_ID       = "<your-version-id>"
$CAMERA_CONFIG_ID = "<your-camera-config-id>"

$resp  = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/auth/login" `
  -ContentType "application/json" `
  -Body (@{ email = "owner1@retailvision.com"; password = "testpass123" } | ConvertTo-Json)
$TOKEN = $resp.access_token
```

Container names derived from `$STORE_ID` and `$CAMERA_ID`:
- IEP1: `iep1_<your-store-id>_<your-camera-id>`
- IEP2: `iep2_<your-store-id>_<your-camera-id>`

---

## Group A — Database Schema

> **Warning — A1 wipes all Docker volumes.** Run this group only on a clean environment
> or after deliberately discarding existing data.

**A1 — Reset volumes and restart infrastructure**
```powershell
docker compose down -v
docker compose up -d postgres redis minio
Start-Sleep 10
```
Expected: all three services healthy.

**A2 — All required tables exist**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision -c "\dt"
```
Expected: `tracking_history`, `camera_schedules`, and `edge_agents` appear in the list.

**A3 — tracking_history schema is exactly correct**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision -c "\d tracking_history"
```
Expected columns: `id uuid`, `store_id uuid`, `camera_id text`, `local_id uuid`,
`timestamp_ms int8`, `floor_x float8`, `floor_y float8`, `zone_id uuid`,
`bbox_confidence float4`, `bbox_area int4`, `created_at timestamptz`.

**A4 — Required indexes exist**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT indexname FROM pg_indexes WHERE tablename = 'tracking_history';"
```
Expected: `idx_tracking_history_camera_ts` and `idx_tracking_history_store_ts`.

**A5 — No CREATE TABLE remains in IEP2 source**
```powershell
Get-ChildItem -Recurse -Path "services/iep2_vision" -File | Select-String "CREATE TABLE"
```
Expected: no output.

---

## Group B — IEP2 DB Dependencies

Prerequisite: `docker compose up -d postgres redis minio`

**B1 — psycopg2 is gone from IEP2**
```powershell
Get-ChildItem -Recurse -Path "services/iep2_vision" -File | Select-String "psycopg2"
```
Expected: no output.

**B2 — asyncpg is in IEP2 requirements**
```powershell
Select-String -Path "services/iep2_vision/requirements.txt" -Pattern "asyncpg"
```
Expected: `asyncpg==0.29.0`

**B3 — IEP2 runs with a test video without crashing**

The `iep2_vision` compose service has `./testing-data:/workspace/testing-data:ro` mounted.
```powershell
docker compose run --rm iep2_vision python services/iep2_vision/main.py `
  --store-id $STORE_ID --camera-id $CAMERA_ID `
  --source video --video testing-data/Test1/Camera1.mp4
```
Expected: no crash, no psycopg2 import errors. Let it run for ~30 seconds then Ctrl+C.

**B4 — Rows written to tracking_history**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT id, local_id, timestamp_ms, floor_x, floor_y, bbox_confidence, bbox_area FROM tracking_history LIMIT 5;"
```
Expected: `id` and `local_id` are UUID format, `timestamp_ms` is a large integer,
`floor_x`/`floor_y` are NULL (projection not wired yet), `bbox_confidence` is in [0,1],
`bbox_area` is a positive integer.

**B5 — local_id is stored as UUID, not integer**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT pg_typeof(local_id) FROM tracking_history LIMIT 1;"
```
Expected: `uuid`

---

## Group C — Floor Projection

Prerequisite: test video run from Group B has written rows.

**C1 — Without --camera-config-id, floor coords are NULL**
```powershell
docker compose run --rm iep2_vision python services/iep2_vision/main.py `
  --store-id $STORE_ID --camera-id $CAMERA_ID `
  --source video --video testing-data/Test1/Camera1.mp4
```
After 20 seconds Ctrl+C, then:
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT floor_x, floor_y, zone_id FROM tracking_history ORDER BY created_at DESC LIMIT 3;"
```
Expected: all NULL, no errors.

**C2 — Submit homography calibration via EEP API**

Requires 8+ correspondences. Uses an identity-like mapping (pixel / 100 ≈ world meters).
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/draft/camera-configs/$CAMERA_CONFIG_ID/calibration/homography" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      correspondences = @(
          @{ pixel = @(0,   0);   world = @(0.0, 0.0) }
          @{ pixel = @(640, 0);   world = @(6.4, 0.0) }
          @{ pixel = @(640, 480); world = @(6.4, 4.8) }
          @{ pixel = @(0,   480); world = @(0.0, 4.8) }
          @{ pixel = @(320, 240); world = @(3.2, 2.4) }
          @{ pixel = @(160, 120); world = @(1.6, 1.2) }
          @{ pixel = @(480, 120); world = @(4.8, 1.2) }
          @{ pixel = @(320, 360); world = @(3.2, 3.6) }
      )
  } | ConvertTo-Json -Depth 5)
```
Expected: calibration created with homography matrix populated.

Then mark it verified:
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/draft/camera-configs/$CAMERA_CONFIG_ID/calibration/verify" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```
Expected: calibration status becomes `verified`, camera config status becomes `verified`.

**C3 — With --camera-config-id, floor coords are populated**
```powershell
docker compose run --rm iep2_vision python services/iep2_vision/main.py `
  --store-id $STORE_ID --camera-id $CAMERA_ID `
  --camera-config-id $CAMERA_CONFIG_ID `
  --source video --video testing-data/Test1/Camera1.mp4
```
After 20 seconds Ctrl+C, then:
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT floor_x, floor_y, zone_id FROM tracking_history ORDER BY created_at DESC LIMIT 5;"
```
Expected: `floor_x` and `floor_y` are non-NULL floats. `zone_id` is NULL if no zones exist.

**C4 — numpy is used for homography, not cv2.perspectiveTransform**
```powershell
Get-ChildItem -Recurse -Path "services/iep2_vision/projection" -File | Select-String "perspectiveTransform"
```
Expected: no output.

---

## Group D — Redis Consumer Group

**D1 — No plain xread in IEP2 (xreadgroup only)**
```powershell
Get-ChildItem -Recurse -Path "services/iep2_vision" -File | Select-String "\bxread\b"
```
Expected: no output. (`xreadgroup` matches `xread` by substring — pipe through an additional
filter if needed: `| Where-Object { $_ -notmatch "xreadgroup" }`)

**D2 — Consumer group is created when IEP2 starts**

Open **Terminal 1** — start IEP1 to publish manifests (needs RTSP source or test video):
```powershell
docker compose up iep1_ingestion
```

Wait 10 seconds. Open **Terminal 2** — start IEP2:
```powershell
docker compose up -d iep2_vision
```

Check the consumer group:
```powershell
docker compose exec redis redis-cli XINFO GROUPS "stream:iep1:$CAMERA_ID"
```
Expected: one group named `iep2_workers` with at least one consumer.

**D3 — Pending messages accumulate when IEP2 is killed**
```powershell
docker compose kill iep2_vision
docker compose exec redis redis-cli XPENDING "stream:iep1:$CAMERA_ID" iep2_workers - + 10
```
Expected: pending message entries exist (delivered but not yet ACKed).

**D4 — IEP2 drains pending messages on restart**
```powershell
docker compose up -d iep2_vision
Start-Sleep 10
docker compose exec redis redis-cli XPENDING "stream:iep1:$CAMERA_ID" iep2_workers - + 10
```
Expected: empty list — IEP2 replayed and ACKed all pending messages from before the crash.

**D5 — Offline manifests are ACKed without processing**
```powershell
$stream = "stream:iep1:$CAMERA_ID"
docker run --rm --network retail-edge_default redis:7-alpine `
  redis-cli -h redis XADD $stream "*" `
  manifest '{"status":"offline","frames":[],"batch_number":99,"window_start_ms":0,"window_end_ms":0,"gaps":[],"frame_count":0,"expected_frames":10}'

Start-Sleep 5
docker compose exec redis redis-cli XPENDING "stream:iep1:$CAMERA_ID" iep2_workers - + 10
```
Expected: the offline manifest is not in the pending list — IEP2 ACKed it without inserting
any tracking_history rows.

---

## Group E — IEP1 CLI & Source Options

**E1 — Batch window default is 60 everywhere**
```powershell
Select-String -Path "docker-compose.yml" -Pattern "30\.0"
```
Expected: no output (the 30.0 default has been removed).

```powershell
Select-String -Path "services/iep1_ingestion/app/main.py" -Pattern "window"
```
Expected: `default=60.0` appears in the argparse definition.

**E2 — --help shows both source options**
```powershell
docker compose run --rm iep1_ingestion python -m services.iep1_ingestion.app.main --help
```
Expected: `--rtsp` and `--video` both appear, neither marked as required individually.

**E3 — Mutual exclusion is enforced**
```powershell
# No source → must error
docker compose run --rm iep1_ingestion python -m services.iep1_ingestion.app.main `
  --store-id $STORE_ID --camera-id $CAMERA_ID
```
Expected: exits with error "one of --rtsp or --video is required".

```powershell
# Both sources → must error
docker compose run --rm iep1_ingestion python -m services.iep1_ingestion.app.main `
  --store-id $STORE_ID --camera-id $CAMERA_ID `
  --rtsp rtsp://fake --video test.mp4
```
Expected: exits with error "--rtsp and --video are mutually exclusive".

**E4 — Frames appear in S3 when run with a video file**

IEP1's compose service has no testing-data mount; add one via the `-v` flag:
```powershell
docker compose run --rm `
  -v "${PWD}/testing-data:/workspace/testing-data:ro" `
  iep1_ingestion python -m services.iep1_ingestion.app.main `
  --store-id $STORE_ID --camera-id $CAMERA_ID `
  --video testing-data/Test1/Camera1.mp4 `
  --fps 5.0 --window 60.0
```
After 10 seconds Ctrl+C, then check S3:
```powershell
docker run --rm --network retail-edge_default `
  -e AWS_ACCESS_KEY_ID=retailvision `
  -e AWS_SECRET_ACCESS_KEY=retailvision_dev `
  amazon/aws-cli s3 ls "s3://retailvision/frames/$CAMERA_ID/" `
  --endpoint-url http://minio:9000
```
Expected: `.jpg` files appear with epoch-ms timestamps as filenames.

**E5 — Manifests appear in the Redis stream**
```powershell
docker compose exec redis redis-cli XRANGE "stream:iep1:$CAMERA_ID" - + COUNT 3
```
Expected: manifest entries with `window_start_ms`, `window_end_ms`, `batch_number`,
`status`, and a populated `frames` list.

---

## Group F — Schedule CRUD API

Prerequisite: EEP up.

**F1 — EEP starts with no import errors**
```powershell
docker compose up -d --build eep
docker compose logs eep | Select-String "error|Error" | Select-Object -First 5
docker compose logs eep | Select-String "Uvicorn running"
```
Expected: no import errors, server listening on port 8000.

**F2 — Create a schedule**
```powershell
$schedule    = Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      camera_config_id = $CAMERA_CONFIG_ID
      days_of_week     = @(0,1,2,3,4)
      start_time       = "08:00"
      end_time         = "20:00"
      is_active        = $true
  } | ConvertTo-Json -Depth 5)
$SCHEDULE_ID = [string]$schedule.id
```
Expected: 201 with `id`, `store_id`, all fields echoed back.

**F3 — List schedules**
```powershell
Invoke-RestMethod -Method GET `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```
Expected: array containing the schedule created in F2.

**F4 — Validation rejects bad input**
```powershell
try {
    Invoke-RestMethod -Method POST `
      -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
      -Headers @{ Authorization = "Bearer $TOKEN" } `
      -ContentType "application/json" `
      -Body (@{
          camera_config_id = $CAMERA_CONFIG_ID
          days_of_week     = @(0, 8)
          start_time       = "20:00"
          end_time         = "08:00"
          is_active        = $true
      } | ConvertTo-Json -Depth 5)
} catch { $_.Exception.Response.StatusCode.value__ }
```
Expected: `422` — `days_of_week` has value 8 (invalid), `end_time` is before `start_time`.

**F5 — Trigger endpoint returns accepted**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "start" } | ConvertTo-Json)
```
Expected: 202 with `status: "accepted"` and `action: "start"`.

---

## Group G — Scheduler Evaluation

Prerequisite: EEP up with scheduler running.

**G1 — Scheduler job is registered on startup**
```powershell
docker compose logs eep | Select-String "Scheduler started|camera_schedule_evaluator"
```
Expected: log line confirming scheduler started and job added.

**G2 — Scheduler fires a start event when the window is active**

Create a schedule whose window covers the current UTC time and today's weekday:
```powershell
$nowDay  = [int](Get-Date).ToUniversalTime().DayOfWeek  # 0=Sunday...6=Saturday
$utcTime = (Get-Date).ToUniversalTime()
$start   = $utcTime.AddMinutes(-5).ToString("HH:mm")   # 5 min ago
$end     = $utcTime.AddHours(1).ToString("HH:mm")       # 1 hour from now

Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{
      camera_config_id = $CAMERA_CONFIG_ID
      days_of_week     = @($nowDay)
      start_time       = $start
      end_time         = $end
      is_active        = $true
  } | ConvertTo-Json -Depth 5)
```

Wait up to 60 seconds for the scheduler to fire:
```powershell
Start-Sleep 65
docker compose logs eep | Select-String "SCHEDULE: start camera"
```
Expected: log line appears with the correct `store_id` and `camera_config_id`.

**G3 — Scheduler fires a stop event when the window closes**

Update the schedule so the window is in the past:
```powershell
Invoke-RestMethod -Method PATCH `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ start_time = "00:00"; end_time = "00:01" } | ConvertTo-Json)
```

Wait for the next scheduler cycle:
```powershell
Start-Sleep 65
docker compose logs eep | Select-String "SCHEDULE: stop camera"
```
Expected: stop log line appears.

**G4 — max_instances=1 prevents concurrent evaluations**
```powershell
docker compose logs eep | Select-String "maximum number of running instances"
```
Expected: if `evaluate_schedules` ever takes longer than 60 seconds, APScheduler logs
a "skipped: maximum number of running instances reached" warning instead of launching
a second instance.

**G5 — Timezone evaluation is correct**

Create a second store in a different timezone (e.g. `Asia/Beirut`, UTC+3). Give it a
schedule whose window only matches Beirut local time — not UTC. Only the store whose
local time falls in the window must log a start event in the next scheduler cycle.
This confirms the evaluator uses each store's own timezone, not UTC.

---

## Group H — Proto Stubs

Requires EEP running.

**H1 — Generated files exist inside the EEP container**
```powershell
docker compose exec eep ls app/grpc_generated/
```
Expected: `__init__.py  agent_pb2.py  agent_pb2_grpc.py`

**H2 — No bare `import agent_pb2` in the stub**
```powershell
docker compose exec eep grep "^import agent_pb2" app/grpc_generated/agent_pb2_grpc.py
```
Expected: no output.

**H3 — Package-qualified import is present**
```powershell
docker compose exec eep grep "grpc_generated import agent_pb2" app/grpc_generated/agent_pb2_grpc.py
```
Expected: exactly one line.

**H4 — Messages are importable and correct**
```powershell
docker compose exec eep python -c "
from app.grpc_generated import agent_pb2, agent_pb2_grpc
hb = agent_pb2.Heartbeat(store_id='s1', agent_version='0.1', timestamp_ms=1000)
print('store_id:', hb.store_id)
print('stub:', agent_pb2_grpc.AgentServiceStub)
"
```
Expected: `store_id: s1` and the stub class — no ImportError.

**H5 — StartCamera carries all required fields**
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
Expected: all three fields printed correctly.

---

## Group I — EEP gRPC Server

**I1 — EEP starts with scheduler and gRPC server**
```powershell
docker compose up -d --build eep
docker compose logs eep | Select-String "gRPC server started|Scheduler started"
```
Expected: two log lines — gRPC on port 50051, scheduler with job registered.

**I2 — Port 50051 is reachable**
```powershell
Test-NetConnection -ComputerName localhost -Port 50051
```
Expected: `TcpTestSucceeded : True`

**I3 — Reflection API lists the service**
```powershell
docker run --rm --network host fullstorydev/grpcurl -plaintext localhost:50051 list
```
Expected: `retailvision.agent.v1.AgentService` in output.

**I4 — Heartbeat accepted; agent marked online**

grpcurl on Windows PowerShell has JSON quoting issues. Use the included Python test client:
```powershell
python test_grpc_heartbeat.py
```
Expected output:
```
[*] Connecting to localhost:50051
[*] store_id = <your-store-id>
[*] Heartbeat sent — holding connection for 15s
[*] Check EEP logs and the edge_agents table now.
[*] Disconnecting.
```
EEP logs must show: `Agent connected`

**I5 — edge_agents row created; goes offline on disconnect**

While I4 is running in another terminal:
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT store_id, status, last_heartbeat_at, agent_version FROM edge_agents;"
```
Expected: one row, `status=online`, `last_heartbeat_at` populated.

Then Ctrl+C the I4 process and wait:
```powershell
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

---

## Group J — Edge Agent

Prerequisite: `docker compose up -d eep postgres redis minio`

**J1 — Build and start the edge agent (dev profile)**
```powershell
docker compose --profile edge up -d --build edge_agent_dev
```
Expected: container starts and stays running.

**J2 — EEP sees the agent connect**
```powershell
Start-Sleep 3
docker compose logs eep | Select-String "Agent connected"
```
Expected: `Agent connected store_id=d313d5a2-...`

**J3 — DB shows online**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT store_id, status, last_heartbeat_at FROM edge_agents;"
```
Expected: `status=online`

**J4 — Stop agent → offline**
```powershell
docker compose --profile edge stop edge_agent_dev
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

**J5 — Restart agent → back to online**
```powershell
docker compose --profile edge start edge_agent_dev
Start-Sleep 5
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=online`

---

## Group K — Debug Endpoint (IEP1 only, no auth required)

Prerequisites: EEP up, `edge_agent_dev` running and connected.

Build the IEP1 image once:
```powershell
docker build -t retailvision-iep1:latest .\services\iep1_ingestion
```

**K1 — Send StartCamera**
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
Expected: `status: sent  action: start`

**K2 — IEP1 container appears**
```powershell
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: `iep1_<STORE_ID>_<CAMERA_ID>` listed. May exit quickly without a live RTSP source —
that is acceptable. The container appearing proves the gRPC wiring works end-to-end.

**K3 — Send StopCamera**
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

**K4 — Container gone**
```powershell
docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: empty output.

---

## Group L — Schedule Trigger (IEP1 + IEP2 via orchestrator)

Prerequisites: everything from Group J + K, plus the IEP2 image built:
```powershell
docker build -t retailvision-iep2:latest .\services\iep2_vision
```

**L1 — Create a schedule**
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
Expected: 201 with the new schedule object.

**L2 — Trigger start → IEP1 + IEP2 both start**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "start" } | ConvertTo-Json)

docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: `status: accepted` and both containers appear.

**L3 — Trigger stop → both containers gone**
```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "stop" } | ConvertTo-Json)

docker ps --filter "name=iep1_" --format 'table {{.Names}}\t{{.Status}}'
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: no iep1_ or iep2_ containers.

---

## Group M — Scheduler Auto-fire

Prerequisites: everything from Group L.

**M1 — Create a schedule whose window opens within 2 minutes**
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
Expected: 201 with schedule created.

**M2 — Scheduler fires and starts the containers**

The scheduler evaluates every 60 seconds. Wait up to 3 minutes from the `start_time` set above.
```powershell
Start-Sleep 90
docker compose logs eep | Select-String "SCHEDULE|Camera workers started"
docker ps --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: `SCHEDULE: start camera` log line appears and IEP2 container starts.

**M3 — No duplicate start on the next cycle**

Verifies `_running_cameras` prevents double-starting.
```powershell
Start-Sleep 65
docker compose logs eep | Select-String "SCHEDULE: start camera"
```
Expected: no new `start camera` log for this camera — scheduler sees it in `_running_cameras`
and skips it.

---

## Group N — End-to-End Pipeline Test

Validates the full chain: schedule trigger → IEP1 (frames to S3 + Redis) → IEP2 (YOLO +
ByteTrack + floor projection) → `tracking_history` rows in PostgreSQL. Nine pytest assertions
across four subsystems: DB, Redis, S3, and container lifecycle.

### Prerequisite: activate the draft version

Group N requires an **active** version because IEP2's floor projector only loads calibration
zones when the version is active. Use the SQL bypass (avoids the floor-plan image upload and
full calibration UI flow):

```powershell
docker compose exec postgres psql -U retailvision -d retailvision -c "
  INSERT INTO floor_plans (version_id, section_id, onboarding_method, image_uploaded,
                           original_s3_key, display_s3_key, width_px, height_px)
    VALUES ('$VERSION_ID', '$SECTION_ID', 'standard', true,
            'test/floor.jpg', 'test/floor.jpg', 640, 480);

  -- Insert calibration only if none exists yet (Group C may have already created one).
  INSERT INTO calibrations (camera_config_id, method, status, is_current,
                            homography_matrix, rms_reprojection_error)
  SELECT '$CAMERA_CONFIG_ID'::uuid, 'homography', 'verified', true,
         '[[1,0,0],[0,1,0],[0,0,1]]'::jsonb, 0.0
  WHERE NOT EXISTS (
    SELECT 1 FROM calibrations WHERE camera_config_id = '$CAMERA_CONFIG_ID'::uuid
  );

  -- Ensure any existing calibration is marked verified.
  UPDATE calibrations
    SET status = 'verified',
        rms_reprojection_error = COALESCE(rms_reprojection_error, 0.0)
    WHERE camera_config_id = '$CAMERA_CONFIG_ID'::uuid AND is_current = true;

  UPDATE camera_configs SET status = 'verified' WHERE id = '$CAMERA_CONFIG_ID';

  UPDATE store_config_versions
    SET status = 'active', active_from = NOW()
    WHERE id = '$VERSION_ID';
"
```

The identity homography maps pixels 1:1 to floor meters — sufficient for non-NULL
`floor_x`/`floor_y` in `tracking_history`.

### Prerequisite: live RTSP source

IEP1 reads from `cloud_stream_url` set in Section 1F (`rtsp://host.docker.internal:8554/test`).
A MediaMTX server must serve a test video on that path. The video must contain at least one
visible person — an empty scene produces zero YOLO detections and zero `tracking_history` rows.

### N1 — Build the test runner image (once)

```powershell
docker build -t retailvision-e2e:latest -f tests/Dockerfile .
```

Installs only test dependencies (`pytest`, `pytest-asyncio`, `asyncpg`, `redis`, `boto3`).
Test code is mounted at runtime — only rebuild when `tests/e2e/requirements.txt` changes.

### N2 — Stop any running pipeline containers

The FloorProjector inside IEP2 loads calibration **once at startup**. If IEP2 was already
running from a previous group before the version was activated in N1, it will have no
projector loaded and will write NULL `floor_x`/`floor_y` forever. Stop everything so the
next start picks up the active version.

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "stop" } | ConvertTo-Json)

Start-Sleep 10
docker ps --filter "name=iep1_" --filter "name=iep2_" --format 'table {{.Names}}\t{{.Status}}'
```
Expected: no iep1_ or iep2_ containers running.

### N3 — Clear prior test data

Groups B and C write rows with `timestamp_ms = 0` (video-source placeholder — now fixed,
but existing rows are already in the table). Truncate before the fresh run so assertions
only cover data produced by this e2e execution.

```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "TRUNCATE tracking_history;"
```

### N4 — Start the pipeline and wait 60 seconds

IEP2 will now start fresh, load calibration from the active version, and write rows with
populated floor coordinates.

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8000/api/store/$SLUG/schedules/$SCHEDULE_ID/trigger" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body (@{ action = "start" } | ConvertTo-Json)
```

Wait one full batch window:
```powershell
Start-Sleep 60
```

After 60 seconds IEP1 will have uploaded at least one batch to S3 and published the manifest
to Redis. IEP2 will have consumed it and written rows to `tracking_history`.

### N5 — Run the e2e pytest suite

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

### N6 — Expected results

All 9 tests must pass:

| Test | What it checks |
|------|----------------|
| `test_rows_exist` | At least one row in `tracking_history` for this camera |
| `test_local_id_is_uuid` | `local_id` is a proper UUID object |
| `test_store_id_matches` | Every row carries the correct `store_id` |
| `test_timestamp_ms_populated` | No NULL or zero `timestamp_ms` |
| `test_floor_coords_populated` | At least some rows have non-NULL `floor_x`/`floor_y` |
| `test_bbox_area_positive` | `bbox_area > 0` for all rows |
| `test_bbox_confidence_range` | `bbox_confidence` in `[0.0, 1.0]` for all rows |
| `test_consumer_group_exists` | Stream `stream:iep1:{camera_id}` has group `iep2_workers` |
| `test_no_pending_messages` | All stream messages ACKed by IEP2 |

### N7 — Teardown

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
Expected: empty output.

Stop the edge agent:
```powershell
docker compose --profile edge stop edge_agent_dev
Start-Sleep 3
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT status FROM edge_agents WHERE store_id = '$STORE_ID';"
```
Expected: `status=offline`

---

---

## Group O — IEP3 Unit Tests

No database or Redis required. Tests run inside the `iep3_reconciliation` container using fake repositories.

**O1 — Build the IEP3 image (once)**
```powershell
docker compose build iep3_reconciliation
```
Expected: build completes without pip errors.

**O2 — Confirm all modules import cleanly**
```powershell
docker compose run --rm iep3_reconciliation python -c "
from app.main import main
from app.coordinator import BatchCoordinator
from app.reconciler import Reconciler
from app.reader import BatchReader
from app.reid.gates import cross_camera_gate
from app.reid.matcher import ReidMatcher
from app.selection import PositionSelector
from app.state import StateManager
from app.repository import Iep3Repository
from app.db import create_pool, close_pool, get_pool
from app.settings import get_settings
print('all imports ok')
"
```
Expected: `all imports ok`. No import errors.

**O3 — Run gate tests (pure function, 8 cases)**
```powershell
docker compose run --rm `
  -v "${PWD}:/workspace" `
  -w /workspace `
  iep3_reconciliation `
  pytest tests/unit/iep3/test_gate.py -v
```
Expected: 8 passed.

**O4 — Run matcher tests (6 cases)**
```powershell
docker compose run --rm `
  -v "${PWD}:/workspace" `
  -w /workspace `
  iep3_reconciliation `
  pytest tests/unit/iep3/test_matcher.py -v
```
Expected: 6 passed. No DB or Redis connection attempts.

**O5 — Run selector tests (5 cases)**
```powershell
docker compose run --rm `
  -v "${PWD}:/workspace" `
  -w /workspace `
  iep3_reconciliation `
  pytest tests/unit/iep3/test_selector.py -v
```
Expected: 5 passed, including `test_resolution_cache_hit_skips_db_query`.

**O6 — Run state machine tests (6 cases)**
```powershell
docker compose run --rm `
  -v "${PWD}:/workspace" `
  -w /workspace `
  iep3_reconciliation `
  pytest tests/unit/iep3/test_state.py -v
```
Expected: 6 passed, including `test_deactivate_before_delete_order`.

**O7 — Run full unit suite (25 cases)**
```powershell
docker compose run --rm `
  -v "${PWD}:/workspace" `
  -w /workspace `
  iep3_reconciliation `
  pytest tests/unit/iep3/ -v
```
Expected: 25 passed. 0 failures. No connection refused errors.

**O8 — No stubs or placeholders remain in IEP3 source**
```powershell
Get-ChildItem -Recurse -Path "services/iep3_reconciliation/app" -File | `
  Select-String "placeholder|# C3:|# C4:|# C5:|# C6:|# C7:|# C8:"
```
Expected: no output.

---

## Group P — IEP3 Integration Test

Tests the full reconciliation pipeline against a live PostgreSQL instance.
No Redis, IEP1, IEP2, or EEP needed. Test data is seeded and cleaned up automatically.

Prerequisite: PostgreSQL running and A1 schema applied.

```powershell
docker compose up -d postgres
Start-Sleep 10
```

**P1 — Run both integration tests**
```powershell
docker compose run --rm `
  --network retail-edge_default `
  -v "${PWD}:/workspace" `
  -w /workspace `
  -e DATABASE_URL="postgresql://retailvision:retailvision_dev@postgres:5432/retailvision" `
  iep3_reconciliation `
  pytest tests/e2e/test_iep3_reconciler.py -v -s
```
Expected:
```
tests/e2e/test_iep3_reconciler.py::test_three_camera_reconciliation PASSED
All invariants verified. Stats: {'known_locals': 0, 'new_locals': 3,
  'new_globals_created': 2, 'positions_written': 2, 'newly_lost': 0, ...}

tests/e2e/test_iep3_reconciler.py::test_lost_then_exited_transitions PASSED
State machine transitions verified: ACTIVE→LOST→EXITED

2 passed in X.XXs
```

**P2 — Verify no test artifacts remain in DB**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT count(*) FROM global_identities; SELECT count(*) FROM global_tracking_history; SELECT count(*) FROM local_centroids;"
```
Expected: counts reflect only real pipeline data. The test store cascade-deleted all seeded rows on teardown.

**P3 — Confirm IEP3 tables exist (prerequisite check)**
```powershell
docker compose exec postgres psql -U retailvision -d retailvision `
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'global_%' ORDER BY table_name;"
```
Expected:
```
 table_name
---------------------------
 global_embeddings
 global_identities
 global_local_mapping
 global_tracking_history
```

**P4 — Start IEP3 and verify it connects to infrastructure**

Set `EXPECTED_CAMERAS` to any UUID value for the smoke test:
```powershell
$env:EXPECTED_CAMERAS = $CAMERA_ID
$env:STORE_ID         = $STORE_ID

docker compose up -d iep3_reconciliation
Start-Sleep 5
docker compose logs iep3_reconciliation | Select-String "IEP3 ready|DB verified|Redis verified"
```
Expected: three log lines in order: DB verified, Redis verified, IEP3 ready.

**P5 — IEP3 exposes no port**
```powershell
docker compose ps iep3_reconciliation
```
Expected: state `Up`, no port column or empty ports. IEP3 is a daemon with no HTTP exposure.

**P6 — Graceful shutdown**
```powershell
docker compose stop iep3_reconciliation
docker compose logs iep3_reconciliation | Select-String "Shutdown signal|shutdown complete"
```
Expected: `Shutdown signal received` followed by `IEP3 shutdown complete.` Exit code 0.

---

## Architecture Reference

| Component | Responsibility |
|-----------|----------------|
| `/api/debug/agent/command` | Auth-free; sends `StartCamera` gRPC → edge agent → IEP1 via Docker. IEP2 not involved. |
| `/store/{slug}/schedules/{id}/trigger` | Requires auth (owner or manager); calls `orchestrator.start_camera_workers()` → IEP1 via edge agent gRPC + IEP2 via EEP Docker socket. |
| `edge_agent_dev` | Uses the `edge` compose profile — always include `--profile edge`. |
| IEP1 image | Must be tagged `retailvision-iep1:latest` (default in `edge_agent_dev` env). |
| IEP2 image | Must be tagged `retailvision-iep2:latest` (default in EEP's `IEP2_IMAGE` env). |
| `_running_cameras` | In-memory set in `camera_scheduler.py`; resets on EEP restart. Prevents double-starts. |
| Draft version | Sufficient for Groups A–M. Group N requires activation for zone loading in IEP2's floor projector. |
| E2E test runner | Built from `tests/Dockerfile`; mounts project root at `/workspace`; connects via `retail-edge_default` network. |
| IEP3 unit tests | Run inside `iep3_reconciliation` container; workspace mounted at `/workspace`; no DB or Redis needed. |
| IEP3 integration tests | Run inside `iep3_reconciliation` container; `DATABASE_URL` set to `postgres` service; seeds and cascades own test data. |
| `stream:iep2:batch_complete` | IEP2 publishes here after each batch (after `_flush_centroids`, before XACK of IEP1 stream). Consumer group: `iep3-{store_id}`. |
| IEP3 `EXPECTED_CAMERAS` | Required env var. Comma-separated `physical_cameras.id` UUIDs. IEP3 fails fast at startup if not set. |
