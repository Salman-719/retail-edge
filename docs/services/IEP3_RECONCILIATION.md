<!--
  Rubric: T3 (IEP independence), T1 (AI depth — this is the brain of the AI pipeline)
-->

# IEP3 — cross-camera reconciliation service

**Location:** `services/iep3_reconciliation/`
**Runs on:** Cloud (one instance per store)
**Depends on:** Server Redis, PostgreSQL

## 1. Role and motivation

IEP3 is the core AI component. It solves the cross-camera identity problem:
given that multiple cameras have each tracked people locally (as local_ids),
IEP3 determines which local tracks across different cameras represent the same
physical person, and merges them into a single global_id with a coherent floor trajectory.

## 2. Input contract

- Reads from: `stream:iep2:batch_complete` on server Redis
- Consumer group: `iep3-store-{store_id}`
- Waits for: all cameras in the store to emit `batch_complete` for the same `window_id`

## 3. Processing algorithm

For each completed window (all cameras reported):
1. **Fetch embeddings** — load `local_centroids` for all local_ids seen in this window
2. **Cosine similarity matrix** — compute pairwise cosine similarity between embeddings from different cameras
3. **Threshold matching** — pairs above threshold (see TRADEOFFS.md §4) are candidate matches
4. **Identity merge** — merge matched local_ids into existing global_id (or create new global_id)
5. **State update** — update `global_identities` state machine (ACTIVE / LOST / EXITED)
6. **Trajectory write** — write canonical floor position per global_id per timestamp to `global_tracking_history`
7. **Orphan sweep** — periodic cleanup of stale partial state from previous crashes

## 4. Global identity state machine

```
[NEW] ──► ACTIVE ──► LOST ──► EXITED
                 └──────────► EXITED (timeout)
```
<!-- TODO: Define transition conditions:
     ACTIVE → LOST: no detection in N windows
     LOST → ACTIVE: re-detected (ReID match)
     LOST → EXITED: not re-detected in M windows -->

## 5. Output contract

### Written to PostgreSQL

- `global_identities` — one row per global person identity
- `global_local_mapping` — links global_id ↔ local_id ↔ camera_id
- `global_embeddings` — per-camera centroid for each global_id
- `global_tracking_history` — canonical floor trajectory

## 6. Error behavior and crash safety

See `docs/decisions/ADR-001-xack-before-processing.md` for the full crash-safety design.

| Error condition | Behavior |
|---|---|
| Crashes mid-batch | XACK-before-processing ensures no duplicate; orphan sweep cleans partial state |
| One camera never sends batch_complete | TODO: timeout after N seconds, proceed with available cameras |
| PostgreSQL transaction fails | Asyncpg wraps each window in a single transaction; rolls back on failure |
| Cosine score below threshold for all candidates | New global_id created for unmatched local_id |

## 7. Independence evidence

- Separate Docker image: `iep3_reconciliation`
- Daemon process — no HTTP port, no shared memory with IEP2
- Communicates only via Redis stream (reads) and PostgreSQL (writes)
- Can be restarted independently — XACK model and orphan sweep guarantee consistency
