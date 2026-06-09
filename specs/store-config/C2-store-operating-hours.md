# C2 — Store Operating Hours as the Master Clock

_One store, one set of hours. The store opens — every camera in the active config comes up,
the edge pipeline starts ingesting, the shift begins. The store closes — everything stops and
IEP5 rolls up the day. No more per-camera schedules to keep in sync; the store's open/close is
the single source of truth that drives cameras, IEP1 ingestion, and the IEP5 shift boundary._

---

## Why this exists

Today each camera carries its own `camera_schedules` row (days + start/end), and the scheduler
([camera_scheduler.py](../../services/eep/app/tasks/camera_scheduler.py)) evaluates them
independently; the shift that triggers IEP5 is inferred from "first camera up → last camera
down." That is N schedules to misconfigure per store and no real notion of "store hours."
**Decision (locked): store operating hours replace per-camera hours.** Cameras inherit the
store's hours; `camera_schedules` is retired.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Granularity | **Per weekday open/close** — 7 rows per store, each with `is_open` + `open_time` + `close_time`. Allows different hours per day and closed days. |
| Versioning | Store-level, **NOT** versioned through draft→publish. Hours change often and must not require a config-version bump. Edited via a direct API (the C3 "edit schedule" path). |
| Weekday index | Python `weekday()` convention: **0 = Monday … 6 = Sunday** (matches the retired `camera_schedules.days_of_week`). |
| Overnight | Supported: if `close_time <= open_time` the window wraps past midnight into the next day. |
| Shift trigger | Unchanged mechanism — store open starts all cameras → store close stops all → existing last-camera-stop fires `close_shift_and_run_iep5`. Hours are the upstream cause; the shift-date logic that preserves the open date across midnight stays. |
| No hours configured | Store treated as **closed** — scheduler does not auto-start cameras. Manual/admin start still possible. |
| Upgrade safety | The migration **seeds** each store's hours from its existing `camera_schedules` (union of days, min open, max close) so upgrading does not silently turn everyone's cameras off. |

## Non-obvious tooling / facts (read these in the code first)

- The scheduler is one APScheduler interval job every `WINDOW_SECONDS`
  ([scheduler.py:16](../../services/eep/app/core/scheduler.py#L16)) calling `evaluate_schedules`.
  It keeps an in-memory `_running_cameras: set[(store_id, camera_config_id)]` and detects shift
  start/end from set transitions ([camera_scheduler.py:294-308](../../services/eep/app/tasks/camera_scheduler.py#L294)).
- Camera start/stop is **per physical camera** via `orchestrator.start_camera_workers` /
  `stop_camera_workers` ([orchestrator.py:139,199](../../services/eep/app/core/orchestrator.py#L139)),
  which send `StartCamera`/`StopCamera` to the Edge Agent (rtsp_url, target_fps, window). The
  edge turns that into the running IEP1/IEP2 for that camera — so **starting a camera IS what
  starts its ingestion**; there is no separate IEP1 trigger to add.
- `_store_shift_start: dict[store_id, date]` preserves the open date across midnight (SPEC-004);
  `_fire_shift_end` launches `shift_closer.close_shift_and_run_iep5`
  ([shift_closer.py:67](../../services/eep/app/core/shift_closer.py#L67)) which closes visits,
  flushes `active_person_state`, then launches IEP5. **Leave this path intact.**
- Pending-version activation (`_activate_pending_versions`) and the k3s restart-race guard via
  `camera_status` are independent — **keep them unchanged**.
- `rebuild_running_cameras()` reconciles in-memory state on EEP restart against Redis-backed
  `camera_status` — must be ported to the new hours-based evaluation.
- Migration head will be **0015** after [B1](../bugfixes-cleanup/B1-audit-action-validation.md);
  this spec adds the **next** number (chain after current head; likely `0016`).

## Architectural map

```
NEW  store_operating_hours (table)         PK (store_id, day_of_week)
       is_open, open_time, close_time
models/store_operating_hours.py  (NEW)     ·  models/camera_schedule.py  (DELETE)
schema.sql                                  +store_operating_hours  −camera_schedules
alembic 00NN  create table → seed from camera_schedules → DROP camera_schedules

tasks/camera_scheduler.py   _LOAD_SQL → store hours + active-version camera_configs
                            evaluate_schedules → evaluate_store_hours (open? start all : stop all)
                            rebuild_running_cameras → hours-based
core/scheduler.py           add_job points at the renamed evaluator
api/routers/operating_hours.py (NEW)  GET / PUT  /store/{slug}/operating-hours
api/routers/schedules.py    (DELETE)  + remove from api/__init__.py
schemas/operating_hours.py  (NEW)
core/shift_closer.py        UNCHANGED   ·   orchestrator.py  UNCHANGED (reused)
```

## Read before implementing

- [tasks/camera_scheduler.py](../../services/eep/app/tasks/camera_scheduler.py) (whole file)
- [core/scheduler.py](../../services/eep/app/core/scheduler.py)
- [core/shift_closer.py:67-128](../../services/eep/app/core/shift_closer.py#L67)
- [api/routers/schedules.py](../../services/eep/app/api/routers/schedules.py) (what is retired)
- [models/camera_schedule.py](../../services/eep/app/models/camera_schedule.py)
- [schema.sql](../../services/eep/schema.sql) (`camera_schedules` CREATE + indexes)

## Rules (verifiable)

1. **Table `store_operating_hours`** (migration + `schema.sql`):
   `store_id UUID FK stores(id) ON DELETE CASCADE`, `day_of_week SMALLINT CHECK 0..6`,
   `is_open BOOLEAN NOT NULL DEFAULT FALSE`, `open_time TIME`, `close_time TIME`,
   `updated_at TIMESTAMPTZ`. `PRIMARY KEY (store_id, day_of_week)`. `open_time`/`close_time`
   nullable only when `is_open=false`; when `is_open=true` both required (app-validated).
2. **Migration ordering**: (a) create the table; (b) **seed** — for each store with active
   `camera_schedules`, insert 7 rows: a day is `is_open=true` if any schedule covers it, with
   `open_time = MIN(start_time)` and `close_time = MAX(end_time)` across that store's schedules
   for that day (fallback: a single union window if per-day detail is unavailable); days with no
   coverage → `is_open=false`. (c) `DROP TABLE camera_schedules`. Forward-only; document that
   downgrade re-creates `camera_schedules` empty (data not restored).
3. **Scheduler rewrite** (`camera_scheduler.py`): replace `_LOAD_SQL` with a query that returns,
   per active store: its `store_operating_hours` rows + timezone, and **all camera_configs of the
   store's ACTIVE version** (`store_config_versions.status='active'`). The evaluator:
   - Compute `store_open(now_local)` from the day's row (and the previous day's row if it wraps
     past midnight): `if close > open: open <= now < close; else: now >= open or now < close`.
     `is_open=false` or no row ⇒ closed.
   - For each active-version camera_config: `store_open and key∉running → start`;
     `not store_open and key∈running → stop`. Reuse `_on_camera_start/_on_camera_stop`,
     `_running_cameras`, the `camera_status` restart-race guard, and the shift start/end
     transition block **as-is**.
   - Rename `evaluate_schedules → evaluate_store_hours`; update `scheduler.add_job` + log line.
4. **`rebuild_running_cameras`**: port to evaluate store-openness (not per-camera schedule) when
   pre-marking already-running cameras on EEP restart.
5. **API** (`operating_hours.py`, registered in `api/__init__.py`):
   - `GET /store/{slug}/operating-hours` → all 7 days (fill missing days as `is_open=false`).
   - `PUT /store/{slug}/operating-hours` → replace-all: array of 7 `{day_of_week, is_open,
     open_time, close_time}`. Validate: every day 0..6 present exactly once; if `is_open`,
     times required and `open_time != close_time`. Gate `require_owner_or_manager` (admin passes
     via [A1](../admin-rbac/A1-authz-core.md)). Write audit `operating_hours_updated`.
6. **Audit**: add `operating_hours_updated` to `AUDIT_ACTIONS`
   ([B1](../bugfixes-cleanup/B1-audit-action-validation.md)). No DB enum to touch.
7. **Remove the `schedules` router** from `api/__init__.py` and delete the file + the
   `CameraSchedule` model. Grep the repo (frontend `api.js`, Postman) for `/schedules` and list
   any remaining callers in the PR description; the frontend camera-schedule UI is replaced by the
   C1 store-schedule view (separate spec).

## Acceptance (verify at end of phase)

- Setting Monday `open=09:00 close=17:00` and waiting for a scheduler tick inside that window
  starts **all** active-version cameras for the store; outside it, all stop, and exactly one
  IEP5 shift-close fires for that store/day.
- An overnight store (`open=18:00 close=02:00`) keeps cameras running across midnight and the
  IEP5 `shift_date` equals the **open** date.
- A store with `is_open=false` for today never auto-starts cameras.
- After `alembic upgrade head` on a DB with existing `camera_schedules`, each store's seeded
  hours reproduce its prior active window (no store goes dark unexpectedly); `camera_schedules`
  is gone.
- `GET`/`PUT /operating-hours` round-trips; `PUT` writes an `operating_hours_updated` audit row.
- EEP restart mid-open-window does not double-send StartCamera (rebuild works).

## Hard constraints & anti-patterns

- **Do NOT** keep `camera_schedules` alive "just in case" — two schedule sources is the exact
  drift this removes. One source: `store_operating_hours`.
- **Do NOT** version operating hours through draft→publish. They are store-level and edited live.
- **Do NOT** change `shift_closer` or the shift-date-across-midnight logic — only the *cause*
  (store hours) changes, not the closing sequence.
- **Do NOT** start cameras outside the active config version — always enumerate the **active**
  version's camera_configs, never a draft's.
- **Do NOT** block the scheduler tick on start/stop or shift-close work — keep the existing
  background-task / best-effort patterns.
- Weekday index stays 0=Mon..6=Sun everywhere (DB, API, scheduler) — do not silently switch to
  Sunday-first.

## Pinned versions

Python 3.11 · PostgreSQL 16 · `APScheduler==3.10.x` (as installed) ·
`sqlalchemy[asyncio]==2.0.30` · `asyncpg==0.29.0` · `alembic==1.13.1` · `fastapi==0.115.0`.
Timezone math via stdlib `zoneinfo` (already used).

## Hand-off to later CAT C specs

- **C1** (store-config split view) renders/edit these hours in the "Store Schedule" panel and
  reads them via `GET /operating-hours`.
- **C3** (edit-config menu) wires the "Edit schedule" choice straight to the `PUT` above —
  no draft/publish round-trip.
