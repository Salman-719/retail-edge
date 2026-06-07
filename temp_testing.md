# Temp Testing — 2 Cameras, File-Based, Sequential Validation

> Run from `retail-edge/` directory.
> Set session variables first (see bottom of this file).

---

## Prerequisite — Clean State

```powershell
# Remove all cameras from IEP1
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
gs = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/GetStatus', request_serializer=pb2.Empty.SerializeToString, response_deserializer=pb2.Iep1StatusResponse.FromString)
rc = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/RemoveCamera', request_serializer=pb2.RemoveCameraRequest.SerializeToString, response_deserializer=pb2.RemoveCameraResponse.FromString)
for c in gs(pb2.Empty()).cameras:
    rc(pb2.RemoveCameraRequest(camera_id=c.camera_id)); print(f'Removed {c.camera_id[:8]}')
" 2>&1

# Flush Redis streams
docker exec retail-edge-redis-1 redis-cli --scan --pattern "stream:iep1:*" | ForEach-Object { docker exec retail-edge-redis-1 redis-cli DEL $_ }
docker exec retail-edge-redis-1 redis-cli DEL "stream:iep2:batch_complete"

# Stop any running IEP2 containers
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop iep2_vision
docker rm -f iep2-cam2 2>$null
```

---

## Step 1 — Verify video files are accessible inside IEP1

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import cv2, os
for path in ['/workspace/testing-data/Test1/Camera1.mp4', '/workspace/testing-data/Test1/Camera2.mp4']:
    exists = os.path.exists(path)
    if exists:
        cap = cv2.VideoCapture(path)
        ok, _ = cap.read()
        cap.release()
        print(f'OK    {path}  readable={ok}')
    else:
        print(f'FAIL  {path}  NOT FOUND')
" 2>&1
```

Expected: both paths show `readable=True`.

---

## Step 2 — Insert `camera_runtime_sessions` rows

Required so IEP3 can resolve `camera_config_id` per camera for floor position scoring.

```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
INSERT INTO camera_runtime_sessions (physical_camera_id, store_id, camera_config_id, started_at)
VALUES
  ('$CAMERA_ID_1'::uuid, '$STORE_ID'::uuid, '$CAMERA_CONFIG_ID_1'::uuid, now()),
  ('$CAMERA_ID_2'::uuid, '$STORE_ID'::uuid, '$CAMERA_CONFIG_ID_2'::uuid, now())
ON CONFLICT DO NOTHING;
SELECT physical_camera_id, camera_config_id, started_at
FROM camera_runtime_sessions WHERE store_id='$STORE_ID';
"
```

Expected: 2 rows, one per camera.

---

## Step 3 — Add cam1 to IEP1 and verify capture

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc, time
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',
    request_serializer=pb2.CameraConfig.SerializeToString,
    response_deserializer=pb2.AddCameraResponse.FromString)
r = ac(pb2.CameraConfig(
    camera_id='$CAMERA_ID_1',
    rtsp_url='/workspace/testing-data/Test1/Camera1.mp4',
    target_fps=1.0,
    window_seconds=60.0,
    store_id='$STORE_ID',
), timeout=5.0)
print(f'AddCamera cam1: {chr(34)}OK{chr(34)} if r.success else r.error')
time.sleep(5)
gs = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/GetStatus',
    request_serializer=pb2.Empty.SerializeToString,
    response_deserializer=pb2.Iep1StatusResponse.FromString)
for c in gs(pb2.Empty()).cameras:
    print(f'{c.camera_id[:8]} status={c.status} last_ts={c.last_frame_ts}')
" 2>&1
```

Expected: `status=capturing`, `last_ts > 0`.

---

## Step 4 — Wait for first IEP1 manifest from cam1

```powershell
"Waiting 70s for first 60-second window..."
Start-Sleep 70
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import redis, json
r = redis.Redis.from_url('redis://redis:6379/0')
cam = '$CAMERA_ID_1'
count = r.xlen(f'stream:iep1:{cam}')
msgs = r.xrange(f'stream:iep1:{cam}', count=1)
if msgs:
    m = json.loads(msgs[0][1][b'manifest'])
    fc = m.get('frame_count', 0)
    st = m.get('status', '?')
    ws = m.get('window_start_ms')
    print(f'PASS cam1: {count} manifest(s)  frames={fc} status={st} window_start={ws}')
else:
    print(f'FAIL: no manifests yet — wait longer and retry')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

Expected: at least 1 manifest, `frame_count=60`, `status=online`.

---

## Step 5 — Start IEP2 for cam1

```powershell
$env:CAMERA_ID        = $CAMERA_ID_1
$env:CAMERA_CONFIG_ID = $CAMERA_CONFIG_ID_1
$env:STORE_ID         = $STORE_ID
$env:WINDOW_SECONDS   = "60"
$env:LOCAL_REDIS_URL  = "redis://redis:6379/0"
$env:SERVER_REDIS_URL = "redis://redis:6379/0"
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d --force-recreate iep2_vision
Start-Sleep 15
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep2_vision --tail 6 2>&1
```

Expected:
```
INFO  iep2.projector  Homography loaded  camera_config_id=<CAMERA_CONFIG_ID_1>
INFO  iep2.runtime    IEP2 daemon SERVING  camera=<CAMERA_ID_1>
INFO  iep2.redis_source  Phase B: reading new messages  stream=stream:iep1:<CAMERA_ID_1>
```

---

## Step 6 — Verify IEP2 output for cam1

Wait ~90 s for a full 60-frame manifest to be processed at 1fps:

```powershell
Start-Sleep 90

# batch_complete published?
docker exec retail-edge-redis-1 redis-cli XLEN "stream:iep2:batch_complete"
# Expected: >= 1

# tracking_history rows with floor coords?
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT local_id) AS unique_locals,
       SUM(CASE WHEN floor_x IS NOT NULL THEN 1 ELSE 0 END) AS with_floor_coords
FROM tracking_history WHERE camera_id='$CAMERA_ID_1';"
# Expected: rows > 0, with_floor_coords = rows (all non-null means homography is working)

# PEL should be 0 (XACK fired after batch_complete)
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/0')
cam = '$CAMERA_ID_1'
pel = r.xpending(f'stream:iep1:{cam}', 'iep2_workers')
print(f'PEL: {pel[chr(112)+chr(101)+chr(110)+chr(100)+chr(105)+chr(110)+chr(103)]} (expect 0)')
" 2>&1
```

---

## Step 7 — Add cam2 to IEP1

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
ac = ch.unary_unary('/retailvision.iep1.v1.Iep1Control/AddCamera',
    request_serializer=pb2.CameraConfig.SerializeToString,
    response_deserializer=pb2.AddCameraResponse.FromString)
r = ac(pb2.CameraConfig(
    camera_id='$CAMERA_ID_2',
    rtsp_url='/workspace/testing-data/Test1/Camera2.mp4',
    target_fps=1.0,
    window_seconds=60.0,
    store_id='$STORE_ID',
), timeout=5.0)
print(f'AddCamera cam2: OK' if r.success else f'FAIL: {r.error}')
" 2>&1
```

---

## Step 8 — Start IEP2 for cam2 (separate container)

```powershell
docker run -d --name iep2-cam2 `
    --network retail-edge_default `
    -v retail-edge_ipc-sockets:/tmp/sockets `
    -v retail-edge_frame-store:/dev/shm/frames `
    -e CAMERA_ID=$CAMERA_ID_2 `
    -e CAMERA_CONFIG_ID=$CAMERA_CONFIG_ID_2 `
    -e STORE_ID=$STORE_ID `
    -e WINDOW_SECONDS=60 `
    -e LOCAL_REDIS_URL=redis://redis:6379/0 `
    -e SERVER_REDIS_URL=redis://redis:6379/0 `
    -e DATABASE_URL_SERVER=postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision `
    retail-edge-iep2_vision:latest
Start-Sleep 15
docker logs iep2-cam2 --tail 5
```

Expected:
```
INFO  iep2.projector  Homography loaded  camera_config_id=<CAMERA_CONFIG_ID_2>
INFO  iep2.runtime    IEP2 daemon SERVING  camera=<CAMERA_ID_2>
```

---

## Step 9 — Verify IEP3 reconciliation with both cameras

IEP3 expects 2 cameras (from active store version). It fires after both report OR after 120s timeout. Wait for one full cycle:

```powershell
Start-Sleep 130

# IEP3 reconciliation log
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep3_reconciliation 2>&1 | Select-String "reconciled|Firing|partial|ERROR" | Select-Object -Last 10

# global_tracking_history — positions from IEP3
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT
    COUNT(*) AS global_positions,
    COUNT(DISTINCT global_id) AS unique_globals,
    COUNT(DISTINCT source_camera) AS cameras_contributed
FROM global_tracking_history WHERE store_id='$STORE_ID';"

# batch_complete stream length
docker exec retail-edge-redis-1 redis-cli XLEN "stream:iep2:batch_complete"
```

Expected:
- IEP3 log: `Batch ... reconciled: {cameras_contributed: 2, positions_written: N}`
- `cameras_contributed = 2`
- `unique_globals >= 1` (if people visible in video)
- `batch_complete` count matches number of manifests processed

---

## Session Variables (restore after docker compose down)

Run this block at the start of every new PowerShell session:

```powershell
$STORE_SLUG        = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT slug FROM stores LIMIT 1;")
$STORE_ID          = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM stores LIMIT 1;")
$VERSION_ACTIVE_ID = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM store_config_versions WHERE store_id='$STORE_ID' AND status='active' LIMIT 1;")
$CAMERA_ID_1       = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM physical_cameras WHERE store_id='$STORE_ID' ORDER BY name LIMIT 1;")
$CAMERA_ID_2       = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM physical_cameras WHERE store_id='$STORE_ID' ORDER BY name OFFSET 1 LIMIT 1;")
$CAMERA_CONFIG_ID_1 = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM camera_configs WHERE version_id='$VERSION_ACTIVE_ID' ORDER BY created_at LIMIT 1;")
$CAMERA_CONFIG_ID_2 = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM camera_configs WHERE version_id='$VERSION_ACTIVE_ID' ORDER BY created_at OFFSET 1 LIMIT 1;")
$CALIBRATION_ID_1  = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM calibrations WHERE camera_config_id='$CAMERA_CONFIG_ID_1' AND is_current=true LIMIT 1;")
$CALIBRATION_ID_2  = (docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -At -c "SELECT id FROM calibrations WHERE camera_config_id='$CAMERA_CONFIG_ID_2' AND is_current=true LIMIT 1;")
$env:STORE_ID      = $STORE_ID

"STORE_SLUG=$STORE_SLUG"
"STORE_ID=$STORE_ID"
"VERSION_ACTIVE_ID=$VERSION_ACTIVE_ID"
"CAMERA_ID_1=$CAMERA_ID_1"
"CAMERA_ID_2=$CAMERA_ID_2"
"CAMERA_CONFIG_ID_1=$CAMERA_CONFIG_ID_1"
"CAMERA_CONFIG_ID_2=$CAMERA_CONFIG_ID_2"
```
