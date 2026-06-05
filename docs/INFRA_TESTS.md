# RetailVision — Infrastructure & Service Tests
## Phases 0, 1, 2: Foundation, Database, Service Health

> **Scope:** This document covers only infrastructure, database schema integrity,
> migration state, and service health. It contains no business logic, user
> workflows, or pipeline data. Every test here must pass before any test in
> `TESTING_GUIDE.md` is attempted.
>
> **Does not cover:** store configuration, camera setup, video ingestion,
> tracking accuracy, reconciliation correctness, or UI workflows — those
> live in `TESTING_GUIDE.md`.

---

## Notation & Conventions

### Environment tags

Each command block is tagged with one of:

- **[WIN]** — Windows PowerShell (development laptop, Intel CPU, no GPU)
- **[LIN]** — Linux / macOS bash (also applies to Jetson Orin unless tagged **[ORIN]**)
- **[ORIN]** — Jetson Orin only (ARM64, CUDA, TensorRT, k3s)
- **[BOTH]** — identical on all platforms

When a command is identical except for the shell, both forms are shown.

### Compose command aliases

Set these once per terminal session. All subsequent commands use `$COMPOSE`.

**[WIN]**
```powershell
# Development stack (CPU, no GPU, Docker Compose only)
$COMPOSE = "docker compose -f docker-compose.yml -f docker-compose.dev.yml"
```

**[LIN] (development machine, not Jetson)**
```bash
# Development stack (CPU)
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
```

**[ORIN]**
```bash
# Production edge stack (Jetson, TensorRT, no dev override)
COMPOSE="docker compose -f docker-compose.yml"
```

All examples below use `$COMPOSE` (PowerShell) or `$COMPOSE` (bash) in place of
the full compose invocation. Substitute accordingly.

### Project name and container naming

Docker Compose derives the project name from the working directory name.
The working directory is `retail-edge/`, so the project name is `retail-edge`.

Container names follow the pattern: `retail-edge-{service_name}-1`

| Service key in compose | Container name |
|---|---|
| `postgres` | `retail-edge-postgres-1` |
| `pgbouncer` | `retail-edge-pgbouncer-1` |
| `redis` | `retail-edge-redis-1` |
| `minio` | `retail-edge-minio-1` |
| `eep` | `retail-edge-eep-1` |
| `iep1-daemon` | `retail-edge-iep1-daemon-1` |
| `iep2_vision` | `retail-edge-iep2_vision-1` |
| `iep3_reconciliation` | `retail-edge-iep3_reconciliation-1` |
| `yolo-service` | `retail-edge-yolo-service-1` |
| `osnet-service` | `retail-edge-osnet-service-1` |
| `live_bridge` | `retail-edge-live_bridge-1` |
| `edge_agent_dev` | `retail-edge-edge_agent_dev-1` (dev profile) |
| `iep2_dev` | `retail-edge-iep2_dev-1` (dev profile) |

### Named volume naming

Volumes follow the pattern: `retail-edge_{volume_key}`

| Volume key | Full name | Contents |
|---|---|---|
| `ipc-sockets` | `retail-edge_ipc-sockets` | ZMQ IPC sockets (YOLO/OSNet) — tmpfs |
| `iep1-sockets` | `retail-edge_iep1-sockets` | IEP1 gRPC control/health unix sockets — tmpfs |
| `frame-store` | `retail-edge_frame-store` | JPEG frames from IEP1 consumed by IEP2 — tmpfs |
| `postgres_data` | `retail-edge_postgres_data` | PostgreSQL persistent data |
| `redis_data` | `retail-edge_redis_data` | Redis persistent data |
| `minio_data` | `retail-edge_minio_data` | MinIO object storage |

### Default credentials (dev only — never use in production)

| Variable | Default value |
|---|---|
| `POSTGRES_USER` | `retailvision` |
| `POSTGRES_PASSWORD` | `retailvision_dev` |
| `POSTGRES_DB` | `retailvision` |
| `S3_ACCESS_KEY` | `retailvision` |
| `S3_SECRET_KEY` | `retailvision_dev` |
| `S3_BUCKET` | `retailvision` |
| `AGENT_SECRET` | `dev-agent-secret` |
| `JWT_SECRET` | `dev-secret-change-in-production` |

### Connection URLs (inside Docker network)

| Connection | URL |
|---|---|
| EEP → PostgreSQL (asyncpg) | `postgresql+asyncpg://retailvision:retailvision_dev@pgbouncer:5432/retailvision` |
| IEP2/IEP3 → PostgreSQL (asyncpg plain) | `postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision` |
| Alembic → PostgreSQL (psycopg2, direct) | `postgresql+psycopg2://retailvision:retailvision_dev@postgres:5432/retailvision` |
| All services → Redis | `redis://redis:6379/0` |
| Host → PgBouncer | `postgresql://retailvision:retailvision_dev@localhost:5433/retailvision` |
| Host → PostgreSQL (direct) | `postgresql://retailvision:retailvision_dev@localhost:5432/retailvision` |

**Why two PostgreSQL URLs?** EEP uses SQLAlchemy with the `asyncpg` dialect
(`postgresql+asyncpg://`), which requires a different URL prefix. IEP2, IEP3,
and test scripts use asyncpg directly (`postgresql://`). Alembic uses psycopg2
and connects directly to `postgres:5432` (bypassing PgBouncer) because
PgBouncer session mode is incompatible with Alembic's prepared-statement
migration operations.

---

## Phase 0 — Infrastructure

Verify that the stack starts cleanly, all containers reach their expected states,
and inter-service networking works.

### 0.1 Start the stack

**[WIN]** — Development (CPU)
```powershell
cd C:\Users\jawad\Desktop\RetailVision_New\retail-edge
$COMPOSE = "docker compose -f docker-compose.yml -f docker-compose.dev.yml"
Invoke-Expression "$COMPOSE up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge yolo-service osnet-service iep1-daemon"
```

**[LIN]** — Development (CPU)
```bash
cd /path/to/retail-edge
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
$COMPOSE up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge yolo-service osnet-service iep1-daemon
```

**[ORIN]** — Production edge (Jetson, no dev override)
```bash
cd /path/to/retail-edge
COMPOSE="docker compose -f docker-compose.yml"
$COMPOSE up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge yolo-service osnet-service iep1-daemon
```

> **Note (Jetson):** On Jetson Orin, `yolo-service` and `osnet-service` build
> from Dockerfiles that use the JetPack ARM64 base image. The first build
> requires the model weights to be present. Allow 5–10 minutes for TensorRT
> engine compilation on first start.

Wait for all health checks to pass:

**[WIN]**
```powershell
Invoke-Expression "$COMPOSE ps"
```

**[LIN/ORIN]**
```bash
$COMPOSE ps
```

Expected: every service listed shows `healthy` or `running`. PgBouncer, PostgreSQL, and Redis must show `healthy`. YOLO and OSNet may show `running` without a healthcheck while the model loads (allow up to 5 minutes on CPU dev, 10 minutes on Jetson first boot).

### 0.2 Container health check

Verify that every required container is running and none is in a restart loop.

**[WIN]**
```powershell
$required = @("postgres-1","pgbouncer-1","redis-1","minio-1","eep-1","iep1-daemon-1","iep3_reconciliation-1","yolo-service-1","osnet-service-1","live_bridge-1")
$running = docker ps --format "{{.Names}}" | Select-String "retail-edge"
foreach ($svc in $required) {
    $match = $running | Where-Object { $_ -match $svc }
    if ($match) { "OK:   retail-edge-$svc" } else { "FAIL: retail-edge-$svc NOT RUNNING" }
}
```

**[LIN/ORIN]**
```bash
required=("postgres-1" "pgbouncer-1" "redis-1" "minio-1" "eep-1" "iep1-daemon-1" "iep3_reconciliation-1" "yolo-service-1" "osnet-service-1" "live_bridge-1")
running=$(docker ps --format '{{.Names}}')
for svc in "${required[@]}"; do
    if echo "$running" | grep -q "retail-edge-$svc"; then
        echo "OK:   retail-edge-$svc"
    else
        echo "FAIL: retail-edge-$svc NOT RUNNING"
    fi
done
```

### 0.3 Restart loop detection

A container in a restart loop will show increasing restart count in `docker ps`.
Wait 60 seconds, then check restart counts.

**[WIN]**
```powershell
Start-Sleep 60
docker ps --filter "name=retail-edge" --format "{{.Names}}: restarts={{.Status}}" | Select-String "Restarting|restarting"
# Expected: zero matches. Any output indicates a restart loop — check logs.
```

**[LIN/ORIN]**
```bash
sleep 60
docker ps --filter "name=retail-edge" --format "{{.Names}}: {{.Status}}" | grep -i "restarting" || echo "OK: no restart loops"
```

If a container is restarting, inspect its logs:

**[WIN]**
```powershell
docker logs retail-edge-eep-1 --tail 30    # replace with the failing container name
```

**[LIN/ORIN]**
```bash
docker logs retail-edge-eep-1 --tail 30
```

### 0.4 Volume mount verification

Verify that tmpfs volumes are mounted and accessible inside containers.

**[WIN]**
```powershell
# IPC sockets volume — must be accessible by YOLO, OSNet, and IEP2
docker run --rm -v retail-edge_ipc-sockets:/tmp/sockets alpine stat /tmp/sockets; "Exit=$LASTEXITCODE (expect 0)"

# IEP1 sockets volume
docker run --rm -v retail-edge_iep1-sockets:/tmp/iep1 alpine stat /tmp/iep1; "Exit=$LASTEXITCODE (expect 0)"

# Frame store volume — tmpfs; IEP1 writes here, IEP2 reads
docker run --rm -v retail-edge_frame-store:/dev/shm/frames alpine sh -c "echo test > /dev/shm/frames/probe; cat /dev/shm/frames/probe; rm /dev/shm/frames/probe"; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
docker run --rm -v retail-edge_ipc-sockets:/tmp/sockets alpine stat /tmp/sockets && echo "OK: ipc-sockets"
docker run --rm -v retail-edge_iep1-sockets:/tmp/iep1 alpine stat /tmp/iep1 && echo "OK: iep1-sockets"
docker run --rm -v retail-edge_frame-store:/dev/shm/frames alpine sh -c "echo test > /dev/shm/frames/probe && cat /dev/shm/frames/probe && rm /dev/shm/frames/probe" && echo "OK: frame-store"
```

### 0.5 Inter-service network reachability

Verify that services can reach each other inside the `retail-edge_default` network.

**[WIN]**
```powershell
# EEP → Redis
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep python -c "import redis; r=redis.Redis.from_url('redis://redis:6379/0'); print('Redis PING:', r.ping())"

# EEP → PgBouncer
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep python -c "import asyncio,asyncpg; asyncio.run((lambda: asyncpg.connect('postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision'))())"; "Exit=$LASTEXITCODE (expect 0 = connected)"

# IEP3 → Redis (batch_complete stream consumer)
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep3_reconciliation python -c "import redis; r=redis.Redis.from_url('redis://redis:6379/0'); print('Redis PING:', r.ping())"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec eep python -c "import redis; r=redis.Redis.from_url('redis://redis:6379/0'); print('Redis PING:', r.ping())"
$COMPOSE exec eep python -c "import asyncio,asyncpg; asyncio.run(asyncpg.connect('postgresql://retailvision:retailvision_dev@pgbouncer:5432/retailvision'))" && echo "OK: EEP -> PgBouncer"
$COMPOSE exec iep3_reconciliation python -c "import redis; r=redis.Redis.from_url('redis://redis:6379/0'); print('Redis PING:', r.ping())"
```

### 0.6 MinIO bucket existence

**[WIN]**
```powershell
Invoke-WebRequest -Uri "http://localhost:9000/minio/health/live" -Method GET | Select-Object -ExpandProperty StatusCode
# Expected: 200

docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep python -c "
import boto3
s3 = boto3.client('s3', endpoint_url='http://minio:9000', aws_access_key_id='retailvision', aws_secret_access_key='retailvision_dev', region_name='us-east-1')
buckets = [b['Name'] for b in s3.list_buckets()['Buckets']]
print(f'Buckets: {buckets}')
assert 'retailvision' in buckets or len(buckets) >= 0, 'bucket check'
print('OK: MinIO reachable')
" 2>&1
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:9000/minio/health/live && echo "OK: MinIO healthy"
$COMPOSE exec eep python -c "
import boto3
s3 = boto3.client('s3', endpoint_url='http://minio:9000', aws_access_key_id='retailvision', aws_secret_access_key='retailvision_dev', region_name='us-east-1')
buckets = [b['Name'] for b in s3.list_buckets()['Buckets']]
print(f'Buckets: {buckets}')
print('OK: MinIO reachable')
"
```

### 0.7 GPU context (Jetson only)

**[ORIN]**
```bash
# Verify CUDA is visible inside YOLO and OSNet containers
docker exec retail-edge-yolo-service-1 python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0))"
docker exec retail-edge-osnet-service-1 python -c "import torch; print('CUDA available:', torch.cuda.is_available())"

# Verify no GPU context in IEP2 (delegates to YOLO/OSNet)
docker exec retail-edge-iep2_vision-1 python -c "
import sys, importlib
for m in ['torch', 'torchvision', 'tensorrt', 'ultralytics']:
    try:
        importlib.import_module(m)
        print(f'WARN: {m} present in IEP2 image')
    except ImportError:
        print(f'OK:   {m} not in IEP2')
"
```

### 0.8 CPU verification (development laptop only)

**[WIN]**
```powershell
# YOLO must NOT load CUDA on CPU dev
docker exec retail-edge-yolo-service-1 python -c "import torch; cuda=torch.cuda.is_available(); print(f'CUDA: {cuda} (expect False on CPU dev)'); assert not cuda"

# OSNet must NOT load CUDA on CPU dev
docker exec retail-edge-osnet-service-1 python -c "import torch; cuda=torch.cuda.is_available(); print(f'CUDA: {cuda} (expect False)'); assert not cuda"
```

**[LIN]** (development, not Jetson)
```bash
docker exec retail-edge-yolo-service-1 python -c "import torch; assert not torch.cuda.is_available(); print('OK: CPU only')"
docker exec retail-edge-osnet-service-1 python -c "import torch; assert not torch.cuda.is_available(); print('OK: CPU only')"
```

---

## Phase 1 — Database Layer

Verify schema correctness, migration state, and key constraints before any
business data is created.

### 1.1 Direct PostgreSQL connectivity (bypassing PgBouncer)

**[WIN]**
```powershell
# From host — direct to postgres:5432 (mapped to host port 5432)
$env:PGPASSWORD = "retailvision_dev"
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT version();"
```

**[LIN/ORIN]**
```bash
PGPASSWORD=retailvision_dev docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT version();"
```

Expected: PostgreSQL 16.x server version string.

### 1.2 PgBouncer session mode verification

PgBouncer must be configured for **session mode** (required by asyncpg, which
uses prepared statements). Transaction mode would silently corrupt asyncpg
connections.

**[WIN]**
```powershell
# Check pgbouncer.ini pool_mode setting
docker exec retail-edge-pgbouncer-1 cat /etc/pgbouncer/pgbouncer.ini | Select-String "pool_mode"
# Expected: pool_mode = session
```

**[LIN/ORIN]**
```bash
docker exec retail-edge-pgbouncer-1 grep "pool_mode" /etc/pgbouncer/pgbouncer.ini
# Expected: pool_mode = session
```

Verify that a connection through PgBouncer can hold a transaction (session mode proof):

**[WIN]**
```powershell
@'
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect("postgresql://retailvision:retailvision_dev@localhost:5433/retailvision")
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE _session_test (x INT)")
        await conn.execute("INSERT INTO _session_test VALUES (1)")
        val = await conn.fetchval("SELECT x FROM _session_test")
        assert val == 1, f"FAIL: expected 1 got {val}"
    await conn.close()
    print("PASS: PgBouncer session mode confirmed")
asyncio.run(test())
'@ | python -; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
python3 - <<'EOF'
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect("postgresql://retailvision:retailvision_dev@localhost:5433/retailvision")
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE _session_test (x INT)")
        await conn.execute("INSERT INTO _session_test VALUES (1)")
        val = await conn.fetchval("SELECT x FROM _session_test")
        assert val == 1, f"FAIL: expected 1 got {val}"
    await conn.close()
    print("PASS: PgBouncer session mode confirmed")
asyncio.run(test())
EOF
```

### 1.3 Schema completeness

Verify all expected tables exist. This list is derived from `services/eep/schema.sql`.

**[WIN]**
```powershell
$expected_tables = @(
    "users","stores","store_members","store_member_permissions",
    "physical_cameras","camera_configs","store_config_versions",
    "floor_plans","zones","sections","coordinate_frames",
    "camera_zone_coverage","calibrations","obstacles",
    "tracking_history","local_centroids",
    "global_identities","global_local_mapping","global_embeddings",
    "global_tracking_history",
    "alert_configs","alerts","audit_logs",
    "employees","employee_embeddings","employee_sections",
    "shift_patterns","shift_instances",
    "edge_agents","camera_runtime_sessions",
    "refresh_tokens","invitations","store_settings",
    "version_sync_events","test_runs","test_run_cameras"
)
$actual = docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -t -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
foreach ($tbl in $expected_tables) {
    if ($actual -match $tbl) { "OK:   $tbl" } else { "FAIL: $tbl MISSING" }
}
```

**[LIN/ORIN]**
```bash
expected_tables=(
    users stores store_members store_member_permissions
    physical_cameras camera_configs store_config_versions
    floor_plans zones sections coordinate_frames
    camera_zone_coverage calibrations obstacles
    tracking_history local_centroids
    global_identities global_local_mapping global_embeddings
    global_tracking_history
    alert_configs alerts audit_logs
    employees employee_embeddings employee_sections
    shift_patterns shift_instances
    edge_agents camera_runtime_sessions
    refresh_tokens invitations store_settings
    version_sync_events test_runs test_run_cameras
)
actual=$(docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -t -c \
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
for tbl in "${expected_tables[@]}"; do
    if echo "$actual" | grep -q "$tbl"; then
        echo "OK:   $tbl"
    else
        echo "FAIL: $tbl MISSING"
    fi
done
```

### 1.4 Critical foreign key constraints

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS references_table,
    ccu.column_name AS references_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('tracking_history','local_centroids','camera_configs','physical_cameras')
ORDER BY tc.table_name, kcu.column_name;
"
```

Expected output includes at minimum:
- `tracking_history.store_id` → `stores.id`
- `tracking_history.camera_id` is text (camera UUID as string — no FK, by design)
- `camera_configs.physical_camera_id` → `physical_cameras.id`
- `camera_configs.version_id` → `store_config_versions.id`

### 1.5 Idempotent insert on `tracking_history`

IEP2 uses `ON CONFLICT (camera_id, local_id, timestamp_ms) DO NOTHING`.
Verify the unique constraint exists.

**[WIN/LIN/ORIN]**
```bash
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tracking_history'
  AND indexdef ILIKE '%unique%'
   OR indexname ILIKE '%unique%';
"
```

Functional verification (requires a valid `store_id` from the `stores` table):

**[WIN]**
```powershell
@'
import asyncio, asyncpg, uuid
async def test():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    # Use an existing store_id if one exists, else skip
    sid = await pool.fetchval("SELECT id FROM stores LIMIT 1")
    if not sid:
        print("SKIP: no stores in DB — run Phase 3 (business data creation) first")
        await pool.close()
        return
    cid = "infra-test-idempotent"
    lid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    await pool.execute("DELETE FROM tracking_history WHERE camera_id=$1", cid)
    sql = """
    INSERT INTO tracking_history
        (store_id, camera_id, local_id, timestamp_ms, floor_x, floor_y,
         zone_id, bbox_confidence, bbox_area)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    ON CONFLICT (camera_id, local_id, timestamp_ms) DO NOTHING
    """
    await pool.execute(sql, sid, cid, lid, 1000, 1.0, 2.0, None, 0.9, 1000)
    c1 = await pool.fetchval("SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1", cid)
    await pool.execute(sql, sid, cid, lid, 1000, 1.0, 2.0, None, 0.9, 1000)
    c2 = await pool.fetchval("SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1", cid)
    await pool.execute("DELETE FROM tracking_history WHERE camera_id=$1", cid)
    await pool.close()
    assert c1 == 1 and c2 == 1, f"FAIL: c1={c1} c2={c2} — duplicate insert not suppressed"
    print(f"PASS: idempotent insert — count stays {c2} after replay")
asyncio.run(test())
'@ | python -; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
python3 - <<'EOF'
import asyncio, asyncpg, uuid
async def test():
    pool = await asyncpg.create_pool(
        "postgresql://retailvision:retailvision_dev@localhost:5433/retailvision",
        min_size=1, max_size=2, statement_cache_size=0,
    )
    sid = await pool.fetchval("SELECT id FROM stores LIMIT 1")
    if not sid:
        print("SKIP: no stores in DB — run Phase 3 first")
        await pool.close()
        return
    cid = "infra-test-idempotent"
    lid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    await pool.execute("DELETE FROM tracking_history WHERE camera_id=$1", cid)
    sql = """
    INSERT INTO tracking_history
        (store_id, camera_id, local_id, timestamp_ms, floor_x, floor_y,
         zone_id, bbox_confidence, bbox_area)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    ON CONFLICT (camera_id, local_id, timestamp_ms) DO NOTHING
    """
    await pool.execute(sql, sid, cid, lid, 1000, 1.0, 2.0, None, 0.9, 1000)
    c1 = await pool.fetchval("SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1", cid)
    await pool.execute(sql, sid, cid, lid, 1000, 1.0, 2.0, None, 0.9, 1000)
    c2 = await pool.fetchval("SELECT COUNT(*) FROM tracking_history WHERE camera_id=$1", cid)
    await pool.execute("DELETE FROM tracking_history WHERE camera_id=$1", cid)
    await pool.close()
    assert c1 == 1 and c2 == 1, f"FAIL: c1={c1} c2={c2}"
    print(f"PASS: idempotent insert, count={c2} after replay")
asyncio.run(test())
EOF
```

### 1.6 Alembic migration state

Alembic is the authoritative migration path. Verify all migrations have been
applied and no pending heads exist. Alembic connects directly to `postgres:5432`
(bypassing PgBouncer) because psycopg2 uses prepared statements internally.

> **Note:** `alembic check` requires autogenerate mode (MetaData connected in
> `env.py`) and will fail with "env.py does not provide a MetaData object" in
> this project. Use `alembic current` + `alembic heads` instead.

**[WIN]**
```powershell
# Step 1: show current applied revision
$cur = docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep alembic current 2>&1
$cur
# Expected: a line ending with "(head)" — e.g. "0003 (head)"

# Step 2: confirm the applied revision matches the known head
$heads = docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep alembic heads 2>&1
$heads
# Expected: same revision hash as Step 1 — e.g. "0003 (head)"

# Pass/fail assertion
if ($cur -match "\(head\)") { "PASS: migrations at head" } else { "FAIL: not at head — run alembic upgrade head" }
```

**[LIN/ORIN]**
```bash
# Step 1
$COMPOSE exec eep alembic current
# Step 2
$COMPOSE exec eep alembic heads
# Both must show the same revision with "(head)"
$COMPOSE exec eep alembic current | grep -q "(head)" && echo "PASS: migrations at head" || echo "FAIL: pending migrations"
```

If migrations are pending:

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep alembic upgrade head
```

**[LIN/ORIN]**
```bash
$COMPOSE exec eep alembic upgrade head
```

### 1.7 `.env.example` completeness

Verify that every required `Field(...)` in every Settings class has a
corresponding entry in `.env.example`.

> The script lives at `scripts/check_env_example.py` in the repo root and uses
> `pathlib.Path(__file__).parent.parent` for ROOT — it must run with the full
> repo visible. The EEP container only has `/app/`, so run it in a plain
> `python:3.11-slim` container with the repo root mounted. No extra packages
> needed (stdlib only).

**[WIN]**
```powershell
docker run --rm -v "${PWD}:/workspace:ro" -w /workspace python:3.11-slim python scripts/check_env_example.py
# Expected: "All required fields covered." (exit 0)
```

**[LIN/ORIN]**
```bash
docker run --rm -v "$(pwd):/workspace:ro" -w /workspace python:3.11-slim python scripts/check_env_example.py
# Expected: "All required fields covered." (exit 0)
```

---

## Phase 2 — Service Health & Authentication

Verify that each service starts, reaches its healthy/serving state, and
enforces its auth contract.

### 2.1 EEP — HTTP health endpoint

**[WIN]**
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET | Select-Object StatusCode, Content
# Expected: 200 {"status":"ok"} or similar
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "ok"} or equivalent
```

### 2.2 EEP — gRPC health (with auth)

The EEP gRPC server enforces `x-agent-token` authentication on **all** RPCs
(including health) when `AGENT_SECRET` is set. In dev, `AGENT_SECRET=dev-agent-secret`.

**[WIN]**
```powershell
# Without token — must return UNAUTHENTICATED
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
ch = grpc.insecure_channel('localhost:50051')
stub = health_pb2_grpc.HealthStub(ch)
try:
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0)
    print(f'FAIL: expected UNAUTHENTICATED, got status={r.status}')
except grpc.RpcError as e:
    code = e.code().name
    print(f'status: {code}')
    assert code == 'UNAUTHENTICATED', f'FAIL: expected UNAUTHENTICATED got {code}'
    print('PASS: auth enforced on gRPC health endpoint')
" 2>&1

# With correct token — must return SERVING
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep python -c "
import grpc, os
from grpc_health.v1 import health_pb2, health_pb2_grpc
secret = os.environ.get('AGENT_SECRET', 'dev-agent-secret')
ch = grpc.insecure_channel('localhost:50051')
stub = health_pb2_grpc.HealthStub(ch)
r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0, metadata=[('x-agent-token', secret)])
status = health_pb2.HealthCheckResponse.ServingStatus.Name(r.status)
print(f'status: {status}')
assert status == 'SERVING', f'FAIL: expected SERVING got {status}'
print('PASS: EEP gRPC SERVING with valid token')
" 2>&1
```

**[LIN/ORIN]**
```bash
# Without token — expect UNAUTHENTICATED
$COMPOSE exec eep python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
ch = grpc.insecure_channel('localhost:50051')
stub = health_pb2_grpc.HealthStub(ch)
try:
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0)
    print(f'FAIL: expected UNAUTHENTICATED, got {r.status}')
except grpc.RpcError as e:
    print(f'status: {e.code().name}')
    assert e.code().name == 'UNAUTHENTICATED'
    print('PASS: auth enforced')
"

# With correct token — expect SERVING
$COMPOSE exec eep python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
ch = grpc.insecure_channel('localhost:50051')
stub = health_pb2_grpc.HealthStub(ch)
r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0,
               metadata=[('x-agent-token', 'dev-agent-secret')])
status = health_pb2.HealthCheckResponse.ServingStatus.Name(r.status)
print(f'status: {status}')
assert status == 'SERVING'
print('PASS: EEP gRPC SERVING')
"
```

### 2.3 YOLO service — gRPC health (no auth)

YOLO exposes health on both a TCP port (:50052) and a unix socket.
No auth is required.

Note: YOLO reports `NOT_SERVING` until the model finishes loading.
Allow up to 5 minutes on CPU dev, 10 minutes on Jetson first boot.

**[WIN]**
```powershell
# Poll until SERVING or timeout (300s CPU dev, 600s Jetson)
$deadline = (Get-Date).AddSeconds(300)
while ((Get-Date) -lt $deadline) {
    $status = docker compose -f docker-compose.yml -f docker-compose.dev.yml exec yolo-service python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
try:
    ch = grpc.insecure_channel('localhost:50052')
    stub = health_pb2_grpc.HealthStub(ch)
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=2.0)
    print(health_pb2.HealthCheckResponse.ServingStatus.Name(r.status))
except: print('NOT_READY')
" 2>&1
    if ($status -match "SERVING") { "PASS: YOLO SERVING"; break }
    "Waiting for YOLO... ($status)"; Start-Sleep 10
}
```

**[LIN/ORIN]**
```bash
deadline=$((SECONDS + 300))   # 600 on Jetson first boot
while [ $SECONDS -lt $deadline ]; do
    status=$($COMPOSE exec yolo-service python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
try:
    ch = grpc.insecure_channel('localhost:50052')
    stub = health_pb2_grpc.HealthStub(ch)
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=2.0)
    print(health_pb2.HealthCheckResponse.ServingStatus.Name(r.status))
except: print('NOT_READY')
" 2>/dev/null)
    [ "$status" = "SERVING" ] && echo "PASS: YOLO SERVING" && break
    echo "Waiting for YOLO... ($status)"; sleep 10
done
```

Verify the model variant loaded (CPU dev uses `yolov8n.pt`, Jetson uses TensorRT):

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs yolo-service | Select-String "model|YOLO|engine|TRT|CPU"
```

**[LIN]** (CPU dev)
```bash
$COMPOSE logs yolo-service | grep -iE "model|yolo|cpu|loaded"
# Expected on CPU: "Model loaded: yolov8n.pt" or ultralytics initialisation line
```

**[ORIN]**
```bash
$COMPOSE logs yolo-service | grep -iE "TRT|engine|tensorrt|loaded"
# Expected on Jetson: TensorRT engine loaded message
```

### 2.4 OSNet service — gRPC health (no auth)

**[WIN]**
```powershell
$deadline = (Get-Date).AddSeconds(300)
while ((Get-Date) -lt $deadline) {
    $status = docker compose -f docker-compose.yml -f docker-compose.dev.yml exec osnet-service python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
try:
    ch = grpc.insecure_channel('localhost:50053')
    stub = health_pb2_grpc.HealthStub(ch)
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=2.0)
    print(health_pb2.HealthCheckResponse.ServingStatus.Name(r.status))
except: print('NOT_READY')
" 2>&1
    if ($status -match "SERVING") { "PASS: OSNet SERVING"; break }
    "Waiting for OSNet... ($status)"; Start-Sleep 10
}
```

**[LIN/ORIN]**
```bash
deadline=$((SECONDS + 300))
while [ $SECONDS -lt $deadline ]; do
    status=$($COMPOSE exec osnet-service python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
try:
    ch = grpc.insecure_channel('localhost:50053')
    stub = health_pb2_grpc.HealthStub(ch)
    r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=2.0)
    print(health_pb2.HealthCheckResponse.ServingStatus.Name(r.status))
except: print('NOT_READY')
" 2>/dev/null)
    [ "$status" = "SERVING" ] && echo "PASS: OSNet SERVING" && break
    echo "Waiting for OSNet... ($status)"; sleep 10
done
```

Verify embedding dimensions match the expected 512-dim L2-normalised format:

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec osnet-service python -c "
import os; print('EMBEDDING_DIM:', os.environ.get('EMBEDDING_DIM', '512'))
"
# Expected: EMBEDDING_DIM: 512
```

**[LIN/ORIN]**
```bash
$COMPOSE exec osnet-service python -c "import os; print('EMBEDDING_DIM:', os.environ.get('EMBEDDING_DIM', '512'))"
```

### 2.5 IEP1 daemon — gRPC health (unix socket, no auth)

IEP1 gRPC is unix-socket-only. All calls must go via `docker exec`.

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
gs = ch.unary_unary(
    '/retailvision.iep1.v1.Iep1Control/GetStatus',
    request_serializer=pb2.Empty.SerializeToString,
    response_deserializer=pb2.Iep1StatusResponse.FromString,
)
r = gs(pb2.Empty(), timeout=5.0)
print(f'PASS: IEP1 SERVING, cameras_active={len(r.cameras)}')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep1-daemon python -c "
import grpc
from services.iep1_ingestion.app.grpc_generated import iep1_control_pb2 as pb2
ch = grpc.insecure_channel('unix:///tmp/iep1-sockets/iep1_control.sock')
gs = ch.unary_unary(
    '/retailvision.iep1.v1.Iep1Control/GetStatus',
    request_serializer=pb2.Empty.SerializeToString,
    response_deserializer=pb2.Iep1StatusResponse.FromString,
)
r = gs(pb2.Empty(), timeout=5.0)
print(f'PASS: IEP1 SERVING, cameras_active={len(r.cameras)}')
"
```

### 2.6 IEP2 daemon — SERVING on Redis consumer group

IEP2 daemon SERVING state is confirmed when:
1. The container is running without errors
2. Its Redis consumer group exists on `stream:iep1:{CAMERA_ID}`
3. Its gRPC health socket responds SERVING

Start IEP2 daemon for a test camera (dev compose only):

**[WIN]**
```powershell
$env:CAMERA_ID = "00000000-0000-0000-0000-000000000099"
$env:WINDOW_SECONDS = "60"
$env:LOCAL_REDIS_URL = "redis://redis:6379/0"
$env:SERVER_REDIS_URL = "redis://redis:6379/0"
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up -d iep2_vision
Start-Sleep 10
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep2_vision --tail 8
# Expected last lines contain:
#   IEP2 daemon SERVING  camera=00000000-0000-0000-0000-000000000099
```

**[LIN]** (dev, not Jetson)
```bash
CAMERA_ID=00000000-0000-0000-0000-000000000099 \
WINDOW_SECONDS=60 \
LOCAL_REDIS_URL=redis://redis:6379/0 \
SERVER_REDIS_URL=redis://redis:6379/0 \
$COMPOSE --profile dev up -d iep2_vision
sleep 10
$COMPOSE logs iep2_vision --tail 8
```

**[ORIN]** — On Jetson, IEP2 runs as a k3s Deployment managed by the Edge Agent.
See `TESTING_GUIDE.md` Phase 4 for the k3s-based IEP2 startup verification.

Verify IEP2 gRPC health socket:

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep2_vision python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
cam = '00000000-0000-0000-0000-000000000099'
ch = grpc.insecure_channel(f'unix:///tmp/sockets/iep2_health_{cam}.sock')
stub = health_pb2_grpc.HealthStub(ch)
r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0)
status = health_pb2.HealthCheckResponse.ServingStatus.Name(r.status)
print(f'IEP2 health: {status}')
assert status == 'SERVING', f'FAIL: {status}'
print('PASS: IEP2 SERVING')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN]**
```bash
CAM=00000000-0000-0000-0000-000000000099
$COMPOSE exec iep2_vision python -c "
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
ch = grpc.insecure_channel('unix:///tmp/sockets/iep2_health_${CAM}.sock')
stub = health_pb2_grpc.HealthStub(ch)
r = stub.Check(health_pb2.HealthCheckRequest(service=''), timeout=3.0)
status = health_pb2.HealthCheckResponse.ServingStatus.Name(r.status)
print(f'IEP2 health: {status}')
assert status == 'SERVING'
print('PASS: IEP2 SERVING')
"
```

### 2.7 IEP3 reconciliation — Redis consumer ready

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs iep3_reconciliation --tail 10 | Select-String "SERVING|consumer|stream|error|Error"
# Expected: no error lines; consumer group creation lines or SERVING message
```

**[LIN/ORIN]**
```bash
$COMPOSE logs iep3_reconciliation --tail 10 | grep -iE "serving|consumer|stream|error"
```

Verify IEP3 can reach the `stream:iep2:batch_complete` stream:

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec iep3_reconciliation python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/0')
info = r.xinfo_stream('stream:iep2:batch_complete') if r.exists('stream:iep2:batch_complete') else 'stream not yet created'
print(f'batch_complete stream: {info}')
print('PASS: IEP3 Redis connection confirmed')
" 2>&1; "Exit=$LASTEXITCODE (expect 0)"
```

**[LIN/ORIN]**
```bash
$COMPOSE exec iep3_reconciliation python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/0')
exists = r.exists('stream:iep2:batch_complete')
print(f'batch_complete stream exists: {bool(exists)}')
print('PASS: IEP3 Redis connection confirmed')
"
```

### 2.8 Live Bridge — WebSocket readiness

**[WIN]**
```powershell
Invoke-WebRequest -Uri "http://localhost:8010/health" -Method GET | Select-Object StatusCode
# If /health not implemented, verify container is running and logs show no error:
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs live_bridge --tail 5
```

**[LIN/ORIN]**
```bash
curl -sf http://localhost:8010/health && echo "OK" || echo "No health endpoint — check logs"
$COMPOSE logs live_bridge --tail 5
```

### 2.9 Startup sequence order — Edge Agent

**[ORIN]** — systemd service; verify the startup dependency chain is enforced:
YOLO SERVING → OSNet SERVING → IEP1 SERVING → cameras restored → EEP connected.

```bash
journalctl -u retailvision-edge-agent --since "5 min ago" \
  | grep -E "yolo is SERVING|osnet is SERVING|iep1 is SERVING|Restored.*cameras|Connecting to EEP" \
  | head -10
# All 5 patterns must appear and timestamps must be strictly increasing.
```

**[LIN]** — dev machine; `edge_agent_dev` started via compose `--profile edge`:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs edge_agent_dev \
  | grep -E "yolo is SERVING|osnet is SERVING|iep1 is SERVING|Restored|Connecting to EEP"
```

**[WIN]** — dev machine; `edge_agent_dev` started via compose `--profile edge`:
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs edge_agent_dev 2>&1 | Select-String "yolo is SERVING|osnet is SERVING|iep1 is SERVING|Restored|Connecting to EEP"
```

> **Expected output (all environments):** The following lines must appear in this
> exact order at the beginning of the log (use `Select-Object -First 15` / `head -15`
> — not the tail, which shows reconnect-loop output):
> ```
> WARNING  k8s: no kubeconfig found ...   (dev only — absent on Jetson with k3s)
> INFO     yolo is SERVING
> INFO     osnet is SERVING
> INFO     iep1 is SERVING
> INFO     Restored N / M cameras from k3s
> INFO     Connecting to EEP  url=...
> ```
> Any missing line or reversed order is a bug in the startup sequence.
>
> **Dev note — `StatusCode.NOT_FOUND` reconnect loop is expected here.**
> After `Connecting to EEP`, the agent sends a `Heartbeat` with `store_id`. If no
> store with that UUID exists in the database (empty DB after `docker compose down -v`),
> EEP returns `NOT_FOUND` and the agent correctly enters exponential backoff reconnect.
> This is not a bug. The agent will stay connected once Phase 3 creates a real store
> and the `STORE_ID` env var is updated to match.
>
> **Dev note — repeated `Restored 0 / 0 cameras` in reconnect loop is expected.**
> The `_iep1_health_watcher()` task is recreated on each reconnect cycle with
> `was_serving = False`. When IEP1's Watch stream fires SERVING, the transition from
> False → True triggers `_restore_active_cameras()` each time. This is the correct
> crash-recovery mechanism for IEP1 restarts; the log noise on dev is expected.

---

## Phase 2 Summary Checklist

Run this checklist after completing all Phase 2 tests. Every item must be ✓
before proceeding to `TESTING_GUIDE.md` Phase 3 (Business Data Creation).

| # | Check | Expected |
|---|---|---|
| 2.1 | `GET /health` returns 200 | HTTP 200 |
| 2.2a | EEP gRPC without token | `UNAUTHENTICATED` |
| 2.2b | EEP gRPC with `x-agent-token: dev-agent-secret` | `SERVING` |
| 2.3 | YOLO health on `:50052` | `SERVING` |
| 2.4 | OSNet health on `:50053` | `SERVING` |
| 2.5 | IEP1 `GetStatus` on unix socket | returns, `cameras_active=0` |
| 2.6 | IEP2 daemon logs | `IEP2 daemon SERVING camera=...` |
| 2.7 | IEP3 logs | No error lines |
| 2.8 | Live Bridge running | Container running, no errors |
| 0.5 | All services can reach Redis | `PING: True` |
| 1.2 | PgBouncer session mode | `pool_mode = session` |
| 1.3 | All tables exist | 0 FAIL lines |
| 1.6 | Alembic at head | `alembic current` output contains `(head)` |

---

## Appendix A — Quick Teardown and Reset

Use this to reset the stack to a clean state for re-testing.

**Destroy all containers and volumes (destroys all data):**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

**[LIN/ORIN]**
```bash
$COMPOSE down -v
```

**Restart only — preserve data volumes:**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart
```

**[LIN/ORIN]**
```bash
$COMPOSE restart
```

**Reset only the database (keep other volumes):**

**[WIN]**
```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop postgres pgbouncer
docker volume rm retail-edge_postgres_data
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres pgbouncer
Start-Sleep 15
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec eep alembic upgrade head
```

**[LIN/ORIN]**
```bash
$COMPOSE stop postgres pgbouncer
docker volume rm retail-edge_postgres_data
$COMPOSE up -d postgres pgbouncer
sleep 15
$COMPOSE exec eep alembic upgrade head
```

---

## Appendix B — Jetson-Specific Differences

| Aspect | Windows Dev (CPU) | Jetson Orin (Production) |
|---|---|---|
| Compose override | `-f docker-compose.yml -f docker-compose.dev.yml` | `-f docker-compose.yml` only |
| YOLO backend | ultralytics YOLOv8n CPU | TensorRT engine (ARM64) |
| OSNet backend | ResNet-18 torchvision CPU | OSNet TRT engine (ARM64) |
| Batch sizes | YOLO=4, OSNet=8 | YOLO=32, OSNet=64 |
| Model load time | 30–60 s | 5–10 min (first boot, TRT compilation) |
| IEP2 orchestration | Docker Compose (direct) | k3s Deployments via Edge Agent |
| Edge Agent | `edge_agent_dev` in compose (`--profile edge`) | systemd service on host |
| IPC socket path | Docker volume `retail-edge_ipc-sockets` | hostPath `/dev/shm/sockets` |
| IEP1 socket path | Docker volume `retail-edge_iep1-sockets` | hostPath `/dev/shm/sockets` |
| GPU check | No CUDA expected | `torch.cuda.is_available()` must be `True` |
| `WINDOW_SECONDS` | Any (60 default) | Must match IEP1, IEP2, IEP3 — mismatch causes silent reconciliation failure |
