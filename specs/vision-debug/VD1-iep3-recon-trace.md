# VD1 — IEP3 Reconciliation Trace

_IEP3 already decides why two camera-local tracks are the same person; it just throws the reasoning
away after each batch. Capture it — the camera graph, the spatial votes, the ReID cosines, the
selection scores — into a capped dev-only table, switched on per-run, off in production. This is the
data the "why merged" panels render._

## Non-obvious tooling / facts

- `reconciler._match` ([reconciler.py:224](../../services/iep3_reconciliation/app/reconciler.py#L224))
  already builds `ambiguous_all = [(cam_a, local_a, cam_b, local_b, vote_rate)]` and gets
  `confirmed, ambiguous` from `vote_camera_pair`
  ([spatial_voter.py:52](../../services/iep3_reconciliation/app/spatial_voter.py#L52)), which returns
  sets of `(local_a, local_b, vote_rate)` plus internally has `votes`/`co_visible`.
- ReID fallback cosines + `reid_fallback_threshold` live in `appearance_fallback`; selection
  components in `_selection_score` ([selection.py:34](../../services/iep3_reconciliation/app/selection.py#L34)).
- IEP3 already toggles behavior off a **Redis key** pattern (`inference:device`) — reuse that idiom
  for the trace flag rather than an env restart.
- `global_local_mapping` (local↔global↔camera) is already persisted — the local→global panel needs
  no trace, just a read.
- Migration head advances per implementation order — this adds the next number after whatever is current.

## Architectural map

```
alembic 00NN          CREATE SCHEMA debug; CREATE TABLE debug.recon_trace (capped)
iep3/reconciler.py    when trace flag on: collect graph + votes + reid + selection → bulk insert
iep3/repository.py    write_recon_trace(batch, events)  (best-effort, never blocks reconciliation)
iep3/settings.py      read trace flag from Redis key  iep3:debug_trace:{store_id}
eep dev_pipeline.py   start sets the Redis key; stop clears it
eep dev endpoint      GET /api/debug/dev/iep3/trace?store_id&batch_number?   (admin/DEBUG gated, A4)
```

## Read before implementing

- [reconciler.py:224-270](../../services/iep3_reconciliation/app/reconciler.py#L224) (where votes/ambiguous are known)
- [spatial_voter.py](../../services/iep3_reconciliation/app/spatial_voter.py) (vote_rate/votes/co_visible)
- [selection.py:34-200](../../services/iep3_reconciliation/app/selection.py#L34) (score components)
- the `inference:device` Redis-toggle usage (for the gating idiom)
- [dev_pipeline.py](../../services/eep/app/api/routers/dev_pipeline.py) (start/stop hooks + dev endpoint conventions)

## Rules (verifiable)

1. **Table `debug.recon_trace`** (own `debug` schema so it never pollutes prod analytics):
   `id BIGSERIAL, store_id UUID, batch_number BIGINT, event_type VARCHAR(20)
   CHECK (event_type IN ('graph','spatial_vote','reid_fallback','selection')),
   detail JSONB, created_at TIMESTAMPTZ DEFAULT now()`. Index `(store_id, batch_number)`.
   `detail` shapes per type:
   - `graph`: `{ pairs: [[cam_a, cam_b], ...] }`
   - `spatial_vote`: `{ cam_a, local_a, cam_b, local_b, vote_rate, votes, co_visible, class:'confirmed'|'ambiguous' }`
   - `reid_fallback`: `{ cam_a, local_a, cam_b, local_b, cosine, threshold, matched }`
   - `selection`: `{ global_id, timestamp_ms, source_camera, score, components:{...} }`
2. **Capping**: cap by row count or age per store (e.g., keep the last N batches), pruned on write —
   this is ephemeral debug data, never unbounded. Document the cap.
3. **Gating (Redis)**: IEP3 reads `iep3:debug_trace:{store_id}` each batch; only when set does it
   collect + write the trace. `dev_pipeline /pipeline/start` sets the key; `/stop` clears it. Default
   absent ⇒ no trace ⇒ **zero overhead in production**.
4. **Writer is best-effort**: trace collection/insert must be wrapped so a failure logs and continues
   — it must NEVER block or fail reconciliation (the trace is diagnostic, not authoritative).
5. **Collect from existing values**: do not recompute — capture the `confirmed`/`ambiguous`/
   `vote_rate`/`votes`/`co_visible` the voter already produces, the fallback cosines, and the
   `_selection_score` components, then bulk-insert once per batch.
6. **Dev endpoint** `GET /api/debug/dev/iep3/trace?store_id=&batch_number=` (admin/DEBUG via
   [A4](../admin-rbac/A4-devtools-gating.md)): return trace rows for the store, optionally one batch,
   newest batches first, capped limit. Read-only.

## Acceptance

- With the Redis flag set (via dev start), running two overlapping cameras populates `debug.recon_trace`
  with `graph`, `spatial_vote` (confirmed + ambiguous with real `vote_rate`/`votes`/`co_visible`),
  `reid_fallback` (cosines), and `selection` rows per batch.
- With the flag absent, no rows are written and reconciliation timing is unchanged (spot-check the
  per-batch duration logs).
- A forced trace-write error logs and reconciliation still completes (best-effort proven).
- The dev endpoint returns the trace for a given store/batch; non-admin in prod → 403.
- The table is capped (old batches pruned) — it does not grow without bound across a long session.

## Hard constraints & anti-patterns

- **NEVER** run the trace in a normal production pipeline — Redis-gated, default off, `debug` schema.
- **NEVER** let trace writing block or fail reconciliation — best-effort only.
- **Do NOT** recompute decision values for the trace — capture what the reconciler already computed.
- **Do NOT** make this a hypertable or wire retention policies — a simple capped table is enough.
- Keep the trace per-batch and bulk-written — no per-pair round-trips.

## Pinned versions

Python 3.11 · PostgreSQL 16 · `asyncpg==0.29.0` · `alembic==1.13.1` · `redis[asyncio]==5.0.4` ·
`fastapi==0.115.0`.
