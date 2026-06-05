# RetailVision — Error Backlog

Structured log of every identified issue, root cause, and final fix.
Each entry follows the format:

```
### BUG-NNN — <short title>
**Status:** Open | Fixed | Won't Fix
**Service(s):** <affected services>
**Severity:** Critical | High | Medium | Low
**Symptom:** What the user/system observed
**Root Cause:** Specific file:line and explanation
**Fix:** Minimal correct change applied
**Verification:** How the fix was confirmed
**Notes:** Systemic or architectural implications
```

---

## Open Issues

*(none)*

---

## Fixed Issues

### BUG-001 — PgBouncer image not found on Docker Hub
**Status:** Fixed  
**Service(s):** `docker-compose.yml` → `pgbouncer` service  
**Severity:** Critical (blocks entire stack from starting)  
**Symptom:** `docker compose up` fails with `failed to resolve reference "docker.io/pgbouncer/pgbouncer:1.22.1": not found`  
**Root Cause:** Two compounding issues: (1) `pgbouncer/pgbouncer` is an abandoned image (last tag `1.15.0`, 2020) — wrong namespace entirely. (2) The correct image is `edoburu/pgbouncer`, but its tag format includes a patch suffix (`1.22.1-p0`), not a bare version string (`1.22.1`).  
**Fix:** Changed `docker-compose.yml` line 65: `pgbouncer/pgbouncer:1.22.1` → `edoburu/pgbouncer:1.22.1-p0`. The `edoburu/pgbouncer` image uses identical config paths (`/etc/pgbouncer/pgbouncer.ini`, `/etc/pgbouncer/userlist.txt`) and ships `psql` for the healthcheck. No changes to config files or healthcheck required.  
**Verification:** Re-run `docker compose up -d postgres pgbouncer redis minio eep iep3_reconciliation live_bridge`; pgbouncer should reach healthy status.  
**Notes:** No systemic implications — isolated to wrong image reference in compose.

---

### BUG-002 — YOLO and OSNet services not runnable on x86 / Intel (no Jetson/CUDA)
**Status:** Fixed  
**Service(s):** `yolo-service`, `osnet-service`, `docker-compose.dev.yml`  
**Severity:** Critical (blocks dev stack on any non-Jetson machine)  
**Symptom:** `docker compose build` fails because `nvcr.io/nvidia/l4t-pytorch:r36.2.0-pth2.2-py3` is an ARM64/Jetson-only base image; TRT/pycuda deps are unavailable on x86.  
**Root Cause:** Both inference service Dockerfiles are pinned to the Jetson JetPack base image and require TensorRT + pycuda, which are NVIDIA-GPU/ARM64-only. No CPU fallback existed.  
**Fix:** Created CPU dev variants without changing any production files:
- `services/yolo_service/Dockerfile.dev` — `python:3.11-slim` base, CPU torch, ultralytics `.pt` model
- `services/yolo_service/service_dev.py` — identical ZMQ wire protocol, loads `yolov8n.pt` on CPU
- `services/yolo_service/requirements.dev.txt`
- `services/osnet_service/Dockerfile.dev` — `python:3.11-slim` base, CPU torch+torchvision, ResNet-18 (512-dim avgpool, same L2-norm wire format)
- `services/osnet_service/service_dev.py` — identical ZMQ wire protocol, no TRT/pycuda
- `services/osnet_service/requirements.dev.txt`
- Updated `docker-compose.dev.yml` to override builds for both services + set `ML_SERVICES_TIMEOUT_S=300`  
**Verification:** Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml build yolo-service osnet-service`; both should build successfully on x86.  
**Notes:** ResNet-18 produces valid 512-dim L2-normalised embeddings — full pipeline works end-to-end. ReID matching quality is lower than OSNet but sufficient for dev testing. IEP2, IEP1, EEP, IEP3 are unchanged.

---

### BUG-003 — grpcio 1.64.0 ecosystem conflicts with protobuf==4.25.3; wrong protobuf pin across all services
**Status:** Fixed  
**Service(s):** All `requirements.txt` files across all services  
**Severity:** Critical (blocks Docker build for EEP, Edge Agent, and all services using grpcio packages)  
**Symptom:** `pip install` fails with `ResolutionImpossible` — `grpcio-tools 1.64.0` and `grpcio-reflection 1.64.0` each require `protobuf>=5.26.1` but all services pin `protobuf==4.25.3`.  
**Root Cause (two-part):**  
  1. `grpcio-tools==1.64.0` was listed as a runtime dependency in `eep` and `edge_agent` requirements; it is a codegen-only tool. Removed.  
  2. The `protobuf==4.25.3` pin was incorrect across all services. Confirmed by `agent_pb2.py` header `# Protobuf Python Version: 5.26.1` — stubs were already generated with protobuf 5.x. The entire grpcio 1.64.0 ecosystem (`grpcio-tools`, `grpcio-reflection`, `grpcio-health-checking`) requires `protobuf>=5.26.1`.  
**Fix:**  
  - Removed `grpcio-tools==1.64.0` from `services/eep/requirements.txt` and `services/edge_agent/requirements.txt` (not needed at runtime; stubs are pre-generated).  
  - Upgraded `protobuf==4.25.3` → `protobuf==5.27.2` in all 8 requirements files (eep, edge_agent, iep1_ingestion, iep2_vision, yolo_service, osnet_service, yolo_service/requirements.dev.txt, osnet_service/requirements.dev.txt).  
  - Both stub styles (`agent_pb2.py` serialized-file approach and `iep1_control_pb2.py` dynamic descriptor approach) use APIs available in both protobuf 4.x and 5.x — no stub regeneration needed.  
**Verification:** Re-run `docker compose -f docker-compose.yml -f docker-compose.dev.yml build yolo-service osnet-service eep`; all pip installs should resolve cleanly.  
**Notes:** To regenerate stubs in future: install `grpcio-tools==1.64.0` in a one-off container as documented in the README. IDE "package not installed" hints on requirements.txt files are the local Windows Python linter checking the host environment — not Docker build errors, safely ignored.

---

### BUG-004 — PostgreSQL password mismatch: .env REPLACE_ME placeholders not filled in
**Status:** Fixed  
**Service(s):** `.env`, `pgbouncer/userlist.txt` → `postgres`  
**Severity:** Critical (postgres healthcheck never passes; entire stack stuck)  
**Symptom:** `FATAL: password authentication failed for user "retailvision"` on every PgBouncer→PostgreSQL connection attempt.  
**Root Cause:** `.env` contained template placeholders (`REPLACE_ME`) for `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `JWT_SECRET`, `GRAFANA_PASSWORD`, and all database URLs. Docker Compose reads `.env` and the placeholder value `REPLACE_ME` overrides the `:-default` fallbacks in docker-compose.yml. PostgreSQL initialized the `retailvision` role with password `REPLACE_ME`; PgBouncer's hardcoded `userlist.txt` sends `retailvision_dev` → mismatch.  
**Fix:** Replaced all `REPLACE_ME` values in `.env` with dev defaults matching docker-compose.yml fallbacks: `POSTGRES_PASSWORD=retailvision_dev`, `S3_ACCESS_KEY=retailvision`, `S3_SECRET_KEY=retailvision_dev`, `JWT_SECRET=dev-secret-change-in-production`, `GRAFANA_PASSWORD=retailvision_dev`, and updated all three DATABASE_URL vars with the correct password.  
**Verification:** After `docker compose down -v` (required — postgres_data volume was initialized with wrong password), retry `docker compose up -d ...`; pgbouncer healthcheck should pass within 30 s.  
**Notes:** `docker compose down -v` is mandatory — the postgres_data volume already has the wrong password baked in from the first (failed) run. The volume must be wiped for PostgreSQL to reinitialize with the correct `POSTGRES_PASSWORD`.

---

### BUG-005 — EEP lifespan crash: `No module named 'alembic.config'` — stale image from failed build
**Status:** Fixed  
**Service(s):** `services/eep/` Docker image  
**Severity:** Critical (EEP exits on startup; no REST API or gRPC server)  
**Symptom:** `ModuleNotFoundError: No module named 'alembic.config'` raised inside `_run_migrations()` at lifespan step 1.  
**Root Cause:** `COPY . .` in the EEP Dockerfile places `services/eep/alembic/` (the Alembic migrations directory, which contains `__init__.py`) at `/app/alembic/` inside the container. `uvicorn app.main:app` runs from WORKDIR `/app`, causing Python to add `/app` to `sys.path`. When `_run_migrations()` executes `from alembic.config import Config`, Python resolves `alembic` to `/app/alembic/` (the migrations dir) instead of the installed pip package. The migrations dir has no `config.py` → `ModuleNotFoundError: No module named 'alembic.config'`. A `--no-cache` rebuild made no difference because the collision is architectural, not a build-cache artifact.  
**Fix:** Changed `services/eep/Dockerfile` to replace `COPY . .` with explicit `COPY` directives that place migration scripts at `/app/db_migrations/` instead of `/app/alembic/`. Updated `services/eep/alembic.ini`: `script_location = alembic` → `script_location = db_migrations`. Rebuild required: `docker compose build --no-cache eep`.  
**Verification:** `docker compose logs eep | grep -E "migrations|started|ERROR"` — should show Alembic upgrade completing and EEP serving.  
**Notes:** Any time a pip install fails mid-build, the broken layer may be cached. After fixing requirements.txt, always rebuild with `docker compose build <service>` before restarting.

### BUG-006 — IEP3 crash: `No module named 'pydantic'` — missing dependency in requirements.txt
**Status:** Fixed  
**Service(s):** `services/iep3_reconciliation/requirements.txt`  
**Severity:** Critical (IEP3 exits immediately on startup; no cross-camera reconciliation)  
**Symptom:** `ModuleNotFoundError: No module named 'pydantic'` at import of `app.settings`, which uses `from pydantic import Field, field_validator, model_validator` and `from pydantic_settings import BaseSettings`.  
**Root Cause:** `pydantic` and `pydantic-settings` were omitted from `services/iep3_reconciliation/requirements.txt`. The Dockerfile only installs what's listed; both packages must be explicit since IEP3 has no transitive dep that pulls them in.  
**Fix:** Added `pydantic==2.7.4` and `pydantic-settings==2.2.1` to `services/iep3_reconciliation/requirements.txt`. Rebuild required: `docker compose build iep3_reconciliation`.  
**Verification:** `docker compose logs iep3_reconciliation | head -10` — should show IEP3 starting and verifying DB/Redis.  
**Notes:** No other services affected. pydantic-settings 2.2.1 is consistent with EEP and IEP2.

---

### BUG-007 — Alembic migration 0002 fails: `ADD CONSTRAINT IF NOT EXISTS` requires PostgreSQL 16, but compose uses postgres:15
**Status:** Fixed  
**Service(s):** `docker-compose.yml` → `postgres` service; `services/eep/alembic/versions/0002_constraints.py`  
**Severity:** Critical (EEP crashes on every startup; Alembic never completes past migration 0002)  
**Symptom:** `ERROR: syntax error at or near "NOT"` on `ALTER TABLE tracking_history ADD CONSTRAINT IF NOT EXISTS ...`  
**Root Cause (two-part):**  
  1. `docker-compose.yml` specified `postgres:15-alpine` while the README and codebase target PostgreSQL 16. Fixed: changed to `postgres:16-alpine`.  
  2. `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` is **not valid PostgreSQL syntax in any released version** (PG15 or PG16). Confirmed by running `psql --version` inside the container: PG16.14 is running yet the same `syntax error at or near "NOT"` persists. The migration was written with a non-existent SQL construct.  
**Fix:**  
  - Changed `docker-compose.yml`: `postgres:15-alpine` → `postgres:16-alpine` (matches README).  
  - Rewrote all 4 `ADD CONSTRAINT IF NOT EXISTS` statements in migration 0002 to use the canonical PostgreSQL idempotent pattern: `DO $$ BEGIN ALTER TABLE ... ADD CONSTRAINT ...; EXCEPTION WHEN duplicate_object THEN NULL; END; $$`. This works on all PostgreSQL versions.  
  - EEP rebuild required to pick up the migration change: `docker compose build --no-cache eep`.  
**Verification:** After rebuild, `docker compose up -d eep` — Alembic should log migration 0002 completing without errors.  
**Notes:** `DO $$ ... EXCEPTION WHEN duplicate_object ...` is the idiomatic PostgreSQL approach for idempotent `ADD CONSTRAINT`. No `docker compose down -v` required — PG16 data directory is already initialized cleanly.

---

### BUG-008 — asyncpg + PgBouncer transaction mode incompatibility — intermittent 500s and "prepared statement does/doesn't exist"
**Status:** Fixed  
**Service(s):** asyncpg 0.29.0 + PgBouncer transaction mode  
**Severity:** Critical (intermittent 500 errors on API calls; calendar/onboarding pages broken; "prepared statement does not exist" has no asyncpg recovery path)  
**Symptom:** Intermittent `ERROR: prepared statement "__asyncpg_stmt_N__" already exists` AND `does not exist`. Pages return 500. DB appears unstable.  
**Root Cause:** asyncpg uses the extended query protocol (PARSE → BIND → EXECUTE as separate sub-messages). PgBouncer transaction mode can reassign the server connection between PARSE and BIND — the BIND then reaches a server connection that never saw the PARSE → "does not exist". The "already exists" variant occurs when two asyncpg clients prepare the same counter-derived statement name on the same reused server connection. `statement_cache_size=0` reduces frequency but cannot eliminate the PARSE/BIND split since asyncpg's internal type-introspection queries always use named prepared statements. No server-side transaction-mode fix exists: `DEALLOCATE ALL` between transactions breaks the PARSE/EXECUTE cycle just as badly.  
**Fix:** Changed `infra/pgbouncer/pgbouncer.ini` from `pool_mode = transaction` to `pool_mode = session`. In session mode each asyncpg logical connection holds a dedicated PostgreSQL server connection — PARSE/BIND/EXECUTE always land on the same connection. asyncpg already manages its own connection pool (pool_size + max_overflow), so PgBouncer transaction multiplexing provides no benefit. Also set `server_reset_query = DISCARD ALL` (correct for session mode) and raised `default_pool_size = 50` to accommodate EEP (30) + IEP3 (10) + IEP2 (2) + overhead. Restart: `docker compose restart pgbouncer`.  
**Verification:** All API calls should return correct responses; no more `prepared statement` errors in postgres logs.  
**Notes:** `statement_cache_size=0` on all pools can be relaxed with session mode (prepared statements now live safely for the connection lifetime), but leaving it does no harm.

---

### BUG-009 — All uvicorn logs silenced after Alembic migration: `fileConfig` disables existing loggers
**Status:** Fixed  
**Service(s):** `services/eep/alembic/env.py`  
**Severity:** High (no API access logs, no "Application startup complete", no uvicorn error logs — silent in production)  
**Symptom:** EEP logs stop at `INFO  [alembic.runtime.migration] Will assume transactional DDL.` Subsequent logs ("Application startup complete", all API access lines) never appear. EEP IS serving correctly — only logging is broken.  
**Root Cause:** `alembic/env.py` calls `fileConfig(config.config_file_name)` with the default `disable_existing_loggers=True`. Python's `fileConfig` with this default **disables every logger not listed in `alembic.ini`**. Since Alembic runs inside the uvicorn process (via `run_in_executor`), this permanently disables `uvicorn`, `uvicorn.access`, and `uvicorn.error` loggers for the rest of the process lifetime. All uvicorn output goes silent after the migration step completes.  
**Fix:** Changed `fileConfig(config.config_file_name)` → `fileConfig(config.config_file_name, disable_existing_loggers=False)` in `services/eep/alembic/env.py`. Rebuild required: `docker compose build --no-cache eep`.  
**Verification:** After rebuild, EEP logs should show "Application startup complete." and access log lines for every request.  
**Notes:** This is a well-known Alembic gotcha when running migrations in-process (not in a subprocess). Always set `disable_existing_loggers=False` when calling `fileConfig` in a long-running application.

---

### BUG-013 — IEP3 coordinator stuck in infinite `NOGROUP` loop after Redis stream deletion
**Status:** Fixed  
**Service(s):** `services/iep3_reconciliation/app/coordinator.py`  
**Severity:** High (IEP3 stops reconciling permanently until manually restarted; `batch_complete` entries accumulate unread)  
**Symptom:** IEP3 logs `ERROR XREADGROUP error: NOGROUP No such key 'stream:iep2:batch_complete' or consumer group ... in XREADGROUP` every 5 seconds indefinitely. No reconciliation occurs.  
**Root Cause:** `coordinator.py:126–129` catches `aioredis.ResponseError` and sleeps 5 s before retrying `XREADGROUP`. When the error is `NOGROUP` (stream or consumer group deleted — happens on Redis restart, manual stream flush, or first publish before the stream exists), the retry fails with the same error forever because the group is never recreated. `_ensure_group()` exists and handles recreation correctly but was only called at startup, not on error.  
**Trigger conditions:** Redis restart (data not persisted), `DEL stream:iep2:batch_complete`, Redis failover, any operational stream flush.  
**Fix:** Added `NOGROUP` detection in the except block. When detected, calls `_ensure_group()` (which runs `XGROUP CREATE ... MKSTREAM` tolerating `BUSYGROUP`) before continuing. All other `ResponseError` subtypes keep the existing sleep-and-retry behaviour. No restart or manual intervention required.  
**Verification:** After stream deletion, IEP3 logs `WARNING Consumer group lost — recreating` then `INFO Consumer group created` and resumes reading new messages without restart.

---

### BUG-012 — Draft activation 500: `MultipleResultsFound` on floor plan and camera existence checks
**Status:** Fixed  
**Service(s):** `services/eep/app/api/routers/draft.py`  
**Severity:** Critical (blocks draft activation; store cannot go live)  
**Symptom:** `POST /api/store/{slug}/versions/draft/activate` returns 500. EEP logs `sqlalchemy.exc.MultipleResultsFound: Multiple rows were found when one or none was required` at `draft.py:1579`.  
**Root Cause:** Two boolean existence checks in `activate_draft` use `scalar_one_or_none()`:  
1. Floor plan check (`draft.py:1562`): `select(FloorPlan).where(...)`  
2. Verified-camera check (`draft.py:1579`): `select(CameraConfig).where(status="verified")`  
`scalar_one_or_none()` raises `MultipleResultsFound` when more than one row matches. Both queries are purely boolean ("does at least one row exist?") — with one floor plan per section and one verified camera config per camera this never triggered, but with multiple floor plans or multiple verified camera configs (the normal case after full onboarding) it crashes.  
**Fix:** Changed both queries to `.limit(1)` + `.scalars().first()`. `.scalars().first()` returns the first match or `None`, never raises on multiple rows. `.limit(1)` tells the DB to stop scanning after the first match.  
**Verification:** Draft activation succeeds after the fix with multiple camera configs present.  
**Notes:** `scalar_one_or_none()` is correct only when the query is expected to return at most one row by contract (e.g. PK lookup). For existence checks on non-unique predicates, always use `.scalars().first()` or `EXISTS`.

---

### BUG-011 — EEP gRPC stream crashes on malformed STORE\_ID from edge agent
**Status:** Fixed  
**Service(s):** `services/eep/app/grpc_server/servicer.py`  
**Severity:** High (crashes the gRPC agent stream; edge agent reconnects in a loop with no useful error)  
**Symptom:** EEP logs `ValueError: badly formed hexadecimal UUID string` inside `_upsert_agent`, followed by `WARNI Agent stream error`. The edge agent immediately disconnects and reconnects. No FK violation is logged — the crash happens before the SQL is reached.  
**Root Cause:** `servicer.py:184` — `uuid.UUID(store_id)` is called directly on the raw proto field value with no validation. If `store_id` is an empty string, contains whitespace, or has any formatting other than a bare UUID hex string, `uuid.UUID()` raises `ValueError`. This propagates up through `Connect()` uncaught by the `IntegrityError` except clause, terminating the entire gRPC stream. The `IntegrityError` handler only guards against FK violations from a valid but nonexistent UUID, not against malformed input.  
**Fix:** Added explicit strip and try/except around `uuid.UUID(store_id_clean)` before the SQL block in `_upsert_agent`. Returns `False` and logs a clear `ERROR` message (`"Agent sent malformed store_id — check STORE_ID env var in edge agent container"`) rather than raising. The actual UUID value is logged with `repr()` so any whitespace or quotes are visible.  
**Verification:** With a malformed STORE\_ID (e.g. empty string), EEP now logs the descriptive error and the gRPC stream continues cleanly rather than crashing.  
**Notes:** The root cause in the environment is `STORE_ID` env var not propagating correctly to the edge agent container — e.g. set after container start, whitespace from shell variable expansion, or PowerShell variable type coercion. The guide (`TESTING_GUIDE.md` section after 3.2) now includes a `docker exec ... python -c "repr(os.environ.get('STORE_ID'))"` diagnostic to confirm the actual value before starting the agent.

---

## Won't Fix / By Design

*(none recorded yet)*
