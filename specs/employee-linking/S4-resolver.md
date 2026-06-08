# S4 — Resolver (Linking Engine)

_An EEP background tick that turns `pending` punch_events into links. Positional match
against `global_tracking_history`; on success writes the link, mirrors live state, and
captures the appearance centroid._

## Read before implementing
- [services/eep/app/tasks/camera_scheduler.py](../../services/eep/app/tasks/camera_scheduler.py)
  — the `asyncio.create_task(_run())` tick + `_fire_*` deferred-task pattern (L35–49).
- [services/eep/app/core/shift_closer.py](../../services/eep/app/core/shift_closer.py)
  — retry-tx + `AsyncSessionLocal()` raw-SQL pattern to mirror.
- `services/eep/app/main.py` — lifespan/startup where `camera_scheduler` is launched
  (start the resolver tick alongside it).
- [services/eep/schema.sql](../../services/eep/schema.sql) — `global_tracking_history`
  (L864: `global_id, store_id, timestamp_ms, floor_x, floor_y, zone_id, source_camera`),
  `global_embeddings` (L844: `global_id, camera_id, centroid BYTEA` = float32[2048]),
  `employee_embeddings` (L333: `embedding JSONB`, `source`, `camera_config_id`, `confidence`).

## New module `services/eep/app/core/punch_resolver.py`

### Tick loop
Started in EEP startup; runs every `PUNCH_RESOLVER_INTERVAL_S` (default 20s). One pass:

```
1. Load active stations (the gate):
   SELECT pis.store_id, pis.world_x, pis.world_y, pis.radius_m,
          pis.camera_config_id, pc.id AS phys_cam_id
   FROM punch_in_stations pis
   JOIN store_config_versions scv ON scv.id = pis.version_id AND scv.status = 'active'
   JOIN camera_configs cc ON cc.id = pis.camera_config_id
   JOIN physical_cameras pc ON pc.id = cc.physical_camera_id
   →  map: store_id -> station
   (Stores without an active-version station are skipped entirely — no overhead.)

2. For each such store, load eligible pending punches:
   SELECT * FROM punch_events
   WHERE store_id = $1 AND status = 'pending'
     AND punched_at_ms <= $now_ms - PUNCH_SETTLE_MS         -- IEP3 has reconciled the window
   ORDER BY punched_at_ms ASC
   (Punches whose window isn't settled yet are left for a later tick.)

3. For each eligible punch, attempt a positional match (below). One short tx per punch.
```

### Positional match query
```sql
SELECT gth.global_id,
       sqrt(power(gth.floor_x - $px, 2) + power(gth.floor_y - $py, 2)) AS dist_m,
       abs(gth.timestamp_ms - $t) AS dt
FROM global_tracking_history gth
WHERE gth.store_id = $sid
  AND gth.timestamp_ms BETWEEN $t - $win AND $t + $win      -- PUNCH_MATCH_WINDOW_MS
ORDER BY dist_m ASC, dt ASC
LIMIT 1
```
- `$px,$py` = station `world_x, world_y`; `$t` = `punched_at_ms`; `$win` = `PUNCH_MATCH_WINDOW_MS`.
- **Accept only if `dist_m <= station.radius_m`.** Otherwise it's a near-miss, not a match.
- *Soft camera preference (optional):* tie-break or filter by `gth.source_camera = $phys_cam_id`
  to prefer observations from the punch camera. Keep positional distance primary.

### Conflict guard (multiple punches close together)
Within a single tick, do not link a `global_id` that another punch in the same pass already
claimed for a **different** employee. If the nearest match is already taken, fall through to
"no match this tick" (stays `pending`, retried next tick). Also: if the matched `global_id`
is already linked to a *different* `employee_id` in `global_identities`, treat as no-match
and log a warning (positional ambiguity).

### On match (single transaction)
```sql
-- 1. Link the identity
UPDATE global_identities
   SET is_employee = TRUE, employee_id = $emp
 WHERE global_id = $gid;

-- 2. Mirror to IEP4 live state so alerts/counts reflect it immediately.
UPDATE active_person_state
   SET is_employee = TRUE, employee_id = $emp, updated_at = now()
 WHERE store_id = $sid AND global_id = $gid;

-- 4. Close out the punch
UPDATE punch_events
   SET status = 'linked', linked_global_id = $gid, match_distance_m = $dist,
       attempts = attempts + 1, last_attempt_at = now(), resolved_at = now()
 WHERE id = $punch_id;
```
**Step 3 — capture embedding (Python, not pure SQL):** `global_embeddings.centroid` is raw
`float32[2048]` bytes; `employee_embeddings.embedding` is JSONB. So:
```python
import numpy as np
rows = await conn.fetch(
    "SELECT camera_id, centroid FROM global_embeddings WHERE global_id = $1", gid)
for r in rows:
    vec = np.frombuffer(r["centroid"], dtype="float32").tolist()   # length 2048
    # camera_config_id: resolve physical camera_id (r["camera_id"]) -> camera_configs.id
    # within the active version; if not resolvable, store NULL.
    await conn.execute(
        """INSERT INTO employee_embeddings
               (employee_id, embedding, source, camera_config_id, confidence)
           VALUES ($1, $2::jsonb, 'punch_in', $3, NULL)""",
        emp, json.dumps(vec), cfg_id_or_none)
```
If `global_embeddings` has no rows yet for `$gid` (centroid not flushed), skip the copy —
the link itself (steps 1,2,4) still succeeds. Embedding capture is best-effort for phase 2.

### No match
- If `now_ms - punched_at_ms < PUNCH_MAX_WAIT_MS`: leave `pending`, bump `attempts` and
  `last_attempt_at` (data may still be arriving). 
- Else: `status = 'unmatched'`, `resolved_at = now()` (the employee was never seen near the
  machine — e.g., camera down, occlusion, or they punched remotely).

## Settings (`services/eep/app/core/config.py` or `settings`)
```
PUNCH_RESOLVER_INTERVAL_S = 20        # tick cadence
PUNCH_SETTLE_MS           = 90000     # wait past punch T for IEP3 (60s window) + margin
PUNCH_MATCH_WINDOW_MS     = 10000     # ±10s around T (GTH buckets are 5s)
PUNCH_MAX_WAIT_MS         = 600000    # give up after 10 min -> unmatched
```
All overridable via env. The resolver is **not** DEBUG-gated — it is core to production.

## Startup
In `main.py` lifespan, after the camera scheduler starts, launch:
`asyncio.create_task(punch_resolver.run_forever())`. Guard the loop body in try/except so a
single bad pass never kills the task (log + continue), matching `_fire_shift_end`.

## Acceptance
- With a configured active-version station and tracking data near the point at `≈T`, a
  `pending` punch becomes `linked` within one settle window; `global_identities` for that
  `global_id` shows `is_employee=TRUE, employee_id=<emp>`; `active_person_state` mirrors it;
  `employee_embeddings(source='punch_in')` gains one row per source camera (when centroids
  exist).
- A punch with nobody near the point becomes `unmatched` after `PUNCH_MAX_WAIT_MS`.
- A store with no active-version station never has its punches resolved (gate works).
- Two near-simultaneous punches never link to the same `global_id`.
