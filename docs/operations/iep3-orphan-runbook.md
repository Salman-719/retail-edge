# IEP3 Orphan Sweep — Operational Runbook

See [ADR-001](../decisions/ADR-001-xack-before-processing.md) for the design rationale.

## When to use this runbook

- IEP3 crashed and you want to verify no orphaned state was left behind
- Monitoring alerts on nonzero `deleted_globals` or `deleted_centroids` in sweep logs
- Pre/post-deployment health check

## Step 1 — Detect orphaned global_identities

```sql
SELECT COUNT(*)
FROM global_identities gi
WHERE gi.store_id = '<store_uuid>'
  AND gi.last_seen_ts = gi.first_seen_ts
  AND NOT EXISTS (
      SELECT 1 FROM global_tracking_history gth
      WHERE gth.global_id = gi.global_id
  );
-- Nonzero result = orphaned globals present
-- Expected on healthy system: 0
-- Normal after IEP3 crash: small number, cleared by next sweep
```

## Step 2 — Detect orphaned local_centroids

```sql
SELECT COUNT(*)
FROM local_centroids lc
WHERE lc.store_id = '<store_uuid>'
  AND NOT EXISTS (
      SELECT 1 FROM global_local_mapping glm
      WHERE glm.local_id  = lc.local_id
        AND glm.is_active = TRUE
  );
-- Expected: 0 on healthy system
```

## Step 3 — Trigger manual sweep if needed

```bash
# Connect to IEP3 container and run sweep manually
docker exec iep3-<store_id> python -c "
import asyncio, asyncpg, os
from app.repository import Iep3Repository

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL_SERVER'])
    repo = Iep3Repository(pool)
    deleted_globals, deleted_centroids = await repo.orphan_sweep(os.environ['STORE_ID'])
    print(f'deleted_globals={deleted_globals} deleted_centroids={deleted_centroids}')

asyncio.run(main())
"
```

## Step 4 — Check PEL for stuck messages

```bash
redis-cli -u $SERVER_REDIS_URL \
  XPENDING stream:iep2:batch_complete iep3-<store_id> - + 10
# Expected: (empty list)
# If nonempty: messages were read but XACK never sent — investigate IEP3 logs
# In the XACK-before-processing model this should never happen (it indicates a bug)
```

## Step 5 — Verify stream health

```bash
# Stream length should be bounded by MAXLEN (~1000 max)
redis-cli -u $SERVER_REDIS_URL XLEN stream:iep2:batch_complete
# Expected: <= 1200

# Consumer group lag (messages not yet read by this store's group)
redis-cli -u $SERVER_REDIS_URL XINFO GROUPS stream:iep2:batch_complete
# Find iep3-<store_id> entry, check "lag" field
# Expected: 0 or small (IEP3 keeping up)
# Large lag: IEP3 is behind — check reconciliation duration in logs
```

## What healthy IEP3 startup logs look like

```
INFO  iep3  IEP3 starting  store_id=...  window_seconds=60.0
INFO  iep3  DB verified — all required tables present.
INFO  iep3  Redis verified.
INFO  iep3  Orphan sweep clean  {"store_id": "...", "deleted_globals": 0, "deleted_centroids": 0}
INFO  iep3  PEL health: 0 pending entries for group iep3-...
INFO  iep3  Expected cameras from DB: 4
INFO  iep3  IEP3 ready — listening on stream:iep2:batch_complete
```

## What a post-crash startup looks like (normal)

```
WARNING  iep3  Orphan sweep found stale data  {"store_id": "...", "deleted_globals": 2, "deleted_centroids": 1}
INFO     iep3  PEL health: 0 pending entries for group iep3-...
```

Non-zero sweep counts after a crash are **expected and handled**. Zero PEL count is **always expected**.

## Interpreting periodic sweep logs

Sweep runs every `ORPHAN_SWEEP_INTERVAL_BATCHES` (default: 50) batches. At one batch/minute
this is roughly every 50 minutes. A nonzero count during a periodic sweep (not startup)
indicates IEP3 crashed during the previous sweep interval — investigate recent crash logs.
