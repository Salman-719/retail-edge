# F2 — Camera Health API

_Which cameras are actually feeding the pipeline right now, and is the store's edge device even
talking to us. Read the live status the edge agents already report — don't infer it from
historical session bookkeeping._

## Non-obvious tooling / facts

- `camera_status` ([camera_status.py](../../services/eep/app/grpc_server/camera_status.py)) holds
  the latest `{status, timestamp_ms}` per `physical_camera_id`, reported by edge agents over gRPC,
  rebuilt from Redis on EEP startup. `get_for_store(store_id)` returns all of them. This is the
  authoritative live status (`running` / `starting` / `restarting` / ... / never-reported).
- `GET /store/{slug}/cameras` ([config.py:164](../../services/eep/app/api/routers/config.py#L164))
  already lists the store's physical cameras (id + name) — join names from here.
- `edge_agents` ([edge_agent.py](../../services/eep/app/models/edge_agent.py)) carries device
  `status`, `last_heartbeat_at`, `agent_version` — the device-level health behind the cameras.
- `camera_runtime_sessions` is historical bookkeeping — **not** the source for "online now."

## Architectural map

```
api/routers/live.py   (+, same router as F1)  GET /store/{slug}/cameras/health
schemas/live.py       (+)  CameraHealth { cameras[], agent }
```

## Read before implementing

- [grpc_server/camera_status.py:42-53](../../services/eep/app/grpc_server/camera_status.py#L42)
- [config.py:164](../../services/eep/app/api/routers/config.py#L164) (camera list shape)
- [models/edge_agent.py](../../services/eep/app/models/edge_agent.py)

## Rules (verifiable)

1. **`GET /store/{slug}/cameras/health`** (`get_store_context`; admin via A1) returns
   `{ cameras: [...], agent: {...}, generated_at_ms }`.
2. **Per camera**: `{ physical_camera_id, name, status, last_status_ms, online }` where:
   - `status` from `camera_status.get_for_store` (string); a camera the store has configured but
     that has **never reported** → `status='unknown'`, `online=false`.
   - `online = status == 'running'` (treat `starting`/`restarting`/`unknown`/`offline` as not-online,
     but pass the raw `status` through so the UI can distinguish "starting" from "down").
   - List **all** of the store's physical cameras (from the camera list), left-joined to status —
     a camera with no report still appears.
3. **Agent block**: `{ status, last_heartbeat_at, heartbeat_age_seconds, agent_version, online }`
   where `online = heartbeat within a freshness window` (e.g. ≤ 90s) — surface `heartbeat_age_seconds`
   so the UI can show "last seen 2m ago".
4. `generated_at_ms` for the "last updated" indicator.
5. Read-only; no audit, no migration.

## Acceptance

- A configured-but-never-started camera appears with `status='unknown'`, `online=false`.
- A running camera shows `online=true`; a restarting one shows `online=false` but `status='restarting'`.
- The agent block reflects the real `edge_agents` row; `heartbeat_age_seconds` grows when the device
  goes quiet and `online` flips false past the window.
- Super-admin can call it for any store.

## Hard constraints & anti-patterns

- **Do NOT** derive "online" from `camera_runtime_sessions` — that's history, not live state.
- **Do NOT** hide never-reported cameras — show them as `unknown` so gaps are visible.
- **Do NOT** collapse `starting`/`restarting` into a bare boolean — pass `status` through.
- `camera_status` is per-process in-memory (rebuilt from Redis on startup); if the store has no
  connected agent, return cameras as `unknown` + `agent.online=false` rather than erroring.

## Pinned versions

`fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · `redis[asyncio]==5.0.4` ·
Pydantic v2.
