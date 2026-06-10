# IEP5 — end-of-shift analytics job

**Location:** `services/iep5_analytics/`
**Runs on:** Cloud (one-shot batch Job per `(store, shift_date)`)
**Depends on:** PostgreSQL (TimescaleDB) — read/write via asyncpg
**Launched by:** EEP (`iep5_manager.run_iep5_job`) as a k8s `batch/v1` Job after
the shift-closing transaction (`shift_closer.py`); Docker run in dev.

## 1. Role

IEP5 computes the **shift's analytics rollups** from the raw tracking data once a
shift closes, then exits. It is **not** a daemon — it runs to completion (exit 0 on
success / already-done / empty shift; non-zero on failure) and k8s handles retries
via `backoffLimit`.

Aggregators (`app/aggregators/`): `visits`, `occupancy`, `heatmap`, `zones`,
`sequences`, `employees`, `rollups`. Outputs land in the analytics tables created by
Alembic `0010_analytics_foundation` (TimescaleDB hypertables + continuous
aggregates), e.g. the daily store summary, zone transitions, heatmap buckets.

## 2. Lifecycle

`shift_closer.py` (in EEP) runs the closing transaction (close visit sessions,
flush zone sessions, clear `active_person_state`), then calls
`iep5_manager.run_iep5_job(store_id, shift_date)`. The job re-checks preflight +
idempotency itself (skips if the summary for that `(store, shift_date)` already
exists), so a re-trigger is safe.

## 3. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `STORE_ID` | — (required) | store to analyze |
| `SHIFT_DATE` | — (required) | `YYYY-MM-DD`, the shift **start** date |
| `DATABASE_URL_SERVER` | — (required) | **plain** `postgresql://…` (asyncpg) |
| `WINDOW_SECONDS` | `60` | must match the pipeline |
| `HEATMAP_CELL_SIZE_M` | `0.5` | heatmap grid resolution (metres) |
| `PASSTHROUGH_DWELL_MS` | `30000` | min dwell to count as a visit |
| `DEAD_PERIOD_THRESHOLD` / `DEAD_PERIOD_DURATION_MS` | `3` / `1800000` | dead-period detection |

In k8s these come from `iep5_manager._env()`; the image is `IEP5_IMAGE`
(`{registry}/iep5:{tag}`).

## 4. Deployment

- **Image:** `ghcr.io/<owner>/retailvision/iep5` (multi-arch; CI matrix entry `iep5`).
- **Cloud:** EEP creates `Job iep5-<short>-<shift_date>` (`backoffLimit=3`,
  `ttlSecondsAfterFinished=86400`, `restartPolicy=Never`, SA `iep5`). Inspect with
  `kubectl -n retailvision get jobs -l app=iep5`. See `DEPLOYMENT_GUIDE.md` Part B.
- **Verification:** the Job reaches `Completed`; analytics rows for the shift appear
  (e.g. `SELECT * FROM analytics.daily_store_summary WHERE store_id = …`).
