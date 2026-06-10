# EEP — control plane service

**Location:** `services/eep/`
**Runs on:** Cloud (one instance)
**Exposes:** REST :8000, gRPC :50051

## 1. Role and motivation

EEP is the management brain. It is not a thin CRUD API — it actively orchestrates
the edge pipeline, enforces business schedules, and is the only public-facing
service in the system. All state changes flow through it: store configuration,
camera activation, user access, and IEP4/IEP5 provisioning.

## 2. Orchestration logic

### 2.1 Camera lifecycle management

APScheduler fires `evaluate_store_hours()` every `WINDOW_SECONDS` (default 60 s).
On each tick:

1. Loads `store_operating_hours` rows and all camera configs for every active
   store's active config version.
2. Resolves the current store-local time (per `stores.timezone`, using `zoneinfo`)
   against the day's open/close window, honoring overnight wrap-around.
3. Cameras that should be running but aren't → `orchestrator.start_camera_workers()`
   → gRPC `StartCamera` to Edge Agent.
4. Cameras that should not be running but are → `orchestrator.stop_camera_workers()`
   → gRPC `StopCamera` to Edge Agent.
5. Tracks per-store shift boundaries in memory: when a store transitions from 0
   running cameras to ≥1, the shift start date is recorded; when it transitions
   back to 0, `shift_closer.close_shift_and_run_iep5()` fires as a background task.

On EEP startup, `rebuild_running_cameras()` re-populates the in-memory running-set
from Redis-backed camera status, so the first scheduler tick does not send
redundant `StartCamera` commands for cameras that survived the EEP restart.

### 2.2 Store version activation

`_activate_pending_versions()` runs inside each scheduler tick. When a config
version's `activate_at` timestamp has passed, EEP calls
`orchestrator.activate_version_now()` which: stops the cameras of the old version,
starts the cameras of the new version, and marks the version as active in the DB.

### 2.3 IEP4 and IEP5 provisioning

- **IEP4:** `iep4_manager.apply_iep4(store_id)` is called when a store version is
  activated. It creates (or updates) a k8s `StatefulSet` for `iep4-<short_id>` in
  the `retailvision` namespace, configured from EEP's own DB URL and SMTP env.
- **IEP5:** `iep5_manager.run_iep5_job(store_id, shift_date)` is called by
  `shift_closer` at shift end. It creates a k8s `batch/v1` Job that runs the
  end-of-shift analytics aggregation and exits.

Neither IEP4 nor IEP5 is started directly — EEP provisions them as Kubernetes
workloads, which k8s keeps healthy independently.

### 2.4 Shift closing

`shift_closer.close_shift_and_run_iep5()` runs as a background `asyncio.Task`:
1. Closes open visit sessions and zone sessions for the store in a DB transaction.
2. Clears `active_person_state` for the store.
3. Calls `iep5_manager.run_iep5_job()` to trigger the analytics job.

## 3. REST API routers

| Router | Module | Purpose |
|---|---|---|
| `auth` | `auth.py` | JWT login/refresh, registration, invite acceptance, password reset |
| `stores` | `stores.py` | Create/manage stores (multi-tenant root entity) |
| `config` | `config.py` | Store config read (zones, cameras) — read-only view |
| `draft` | `draft.py` | Versioned floor-plan editor: zones, cameras, calibration, TPS, draft→publish |
| `members` | `members.py` | Org members, roles, invite, remove |
| `employees` | `employees.py` | Staff records, linking to global_ids via punch-in |
| `shifts` | `shifts.py` | Shift patterns and assignments |
| `operating_hours` | `operating_hours.py` | Store open/close schedule (replaces per-camera camera_schedules) |
| `punch` | `punch.py` | Employee punch-in/out events and resolver |
| `live` | `live.py` | Reconciled people counts, KPIs, camera health, edge-agent health |
| `alerts` | `alerts.py` | Active alerts, alert history, resolution, alert-rule CRUD |
| `analytics` | `analytics.py` | Read-only rollup endpoints (store, zone, employee, flow, heatmap) |
| `audit` | `audit.py` | Append-only audit log of privileged actions |
| `settings` | `settings.py` | Store/org settings |
| `debug` | `debug.py` | Dev-only — `DEBUG_MODE` gated; manual pipeline trigger |
| `dev_pipeline` | `dev_pipeline.py` | Dev-only — `DEBUG_MODE` gated; pipeline inspection |

## 4. gRPC server

- Listens on `:50051`.
- **Edge dials out** to EEP — avoids NAT, no inbound ports on store network.
- Bidirectional streaming: EEP pushes `StartCamera`/`StopCamera` commands down the
  open stream; edge sends `Heartbeat` and `CameraStatusReport` up.
- First message from any agent **must** be a `Heartbeat`; EEP aborts with
  `INVALID_ARGUMENT` otherwise.
- Auth: `x-agent-token` metadata checked against `AGENT_SECRET`; empty = dev mode.
- TLS: `GRPC_SERVER_CERT_PATH` + `GRPC_SERVER_KEY_PATH`; empty paths = insecure.

## 5. Input validation and constraints

- All request bodies validated by **Pydantic v2** models (`app/schemas/`).
- Store-scoped routes go through `store_auth` middleware — validates JWT and
  confirms the user is a member of the requested store.
- Rate limiting: per-endpoint limits enforced in `app/core/ratelimit.py`.
- Admin-only routes use `PrivateRoute adminOnly` on the frontend and `Depends` on
  the backend to enforce super-admin membership.

## 6. Error handling

| Scenario | Behavior |
|---|---|
| gRPC stream to edge agent fails / disconnects | Edge Agent reconnects with exponential backoff (1 s → 60 s). EEP has no active retry — it waits for the next incoming stream. |
| `StartCamera` gRPC call raises exception | Logged at ERROR with store_id + camera_config_id. Scheduler will retry on the next tick if the store is still open. |
| APScheduler job raises exception | Caught and logged at EXCEPTION level; the tick is skipped. Next tick fires at the next `WINDOW_SECONDS` interval. |
| Tick takes > 50% of `WINDOW_SECONDS` | Warning logged — not an error, but a signal of DB/gRPC latency. |
| DB write fails in a router | 500 response with structured error envelope (`app/core/errors.py`). No partial writes (SQLAlchemy async transactions). |
| Shift-closer raises exception | Logged at EXCEPTION. IEP5 job is not created. The next scheduler tick will not retry the shift-close (idempotency guard on IEP5 prevents double-runs). |
