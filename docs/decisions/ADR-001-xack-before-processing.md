# ADR-001: XACK Before Processing in IEP3

## Status: Accepted

## Context

IEP3 consumes `batch_complete` messages from `stream:iep2:batch_complete`
via Redis Streams XREADGROUP. The XACK can fire either:
- **(A) Before reconciliation** — message is unretryable on crash
- **(B) After reconciliation** — message replays on crash, but IEP3 has no
  idempotency guard for full reconciliation replays

## Decision

XACK fires immediately on message receipt (option A).

## Rationale

Option B requires full reconciliation idempotency. Reconciliation creates
GlobalIDs (UUIDs), links them to LocalIDs, writes canonical positions, and
transitions FSM states. Making all of this idempotent requires either:
- Deterministic GlobalID derivation (complex, fragile)
- Full replay detection (requires storing processed batch_keys)

Neither is worth the complexity for the expected crash frequency.

Option A accepts silent loss for the rare crash window between XACK and
COMMIT. The compensating control is `run_orphan_sweep()`, which runs on every
IEP3 startup and every `ORPHAN_SWEEP_INTERVAL_BATCHES` thereafter.

## Failure Mode Analysis

```
MODE A — IEP3 crashes after XACK, before on_ready fires:
  Redis:    message gone (XACK sent)
  DB:       nothing written (on_ready never called)
  Footprint: NONE — clean failure, nothing to sweep

MODE B — IEP3 crashes after on_ready, inside Reconciler transaction, before COMMIT:
  Redis:    message gone (XACK sent before on_ready)
  DB:       transaction rolled back automatically by PostgreSQL
  Footprint: NONE — MVCC rollback is atomic

MODE C — IEP3 crashes after COMMIT, before process_batch returns:
  Redis:    message gone
  DB:       all writes committed
  Footprint: NONE — full reconciliation succeeded, crash was post-commit

MODE D — Partial commit:
  Impossible in PostgreSQL with a single transaction.
  PostgreSQL guarantees all-or-nothing within one transaction.

ONLY REAL ORPHAN SOURCE:
  global_identity created in batch N, IEP3 crashes before
  global_tracking_history is written in batch N.
  Result: global_identities row exists (first_seen_ts == last_seen_ts),
  global_tracking_history has NO row for this global_id.
  The orphan sweep targets exactly this case.
```

## Consequences

- Crash between XACK and on_ready: no data loss (nothing was written)
- Crash inside transaction: PostgreSQL rolls back atomically, no orphans
- Crash after COMMIT: full success interrupted late, no orphans
- Only orphan-producing scenario: global_identity created, crash before
  global_tracking_history written (extremely narrow window)

The orphan sweep handles this residual case. See `services/iep3_reconciliation/app/repository.py`
`orphan_sweep()` and the operational runbook at `docs/operations/iep3-orphan-runbook.md`.

## Compensating Controls

1. `orphan_sweep()` runs unconditionally on every IEP3 startup
2. `orphan_sweep()` runs every `ORPHAN_SWEEP_INTERVAL_BATCHES` batches (default: 50)
3. `check_pel_health()` runs on startup — a non-empty PEL indicates a code bug
4. Sweep is always a separate transaction from the reconciliation transaction
5. Sweep is skipped when reconciliation consumed >80% of the window budget
