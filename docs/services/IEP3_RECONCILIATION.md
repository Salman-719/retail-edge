# IEP3 — cross-camera reconciliation service

**Location:** `services/iep3_reconciliation/`
**Runs on:** Cloud (one instance per store)
**Depends on:** Server Redis, PostgreSQL

## 1. Role and motivation

IEP3 is the core AI component. It solves the cross-camera identity problem:
given that multiple cameras have each tracked people locally (as `local_id`s),
IEP3 determines which local tracks across different cameras represent the same
physical person, and merges them into a single `global_id` with a coherent
floor trajectory.

A single camera can track people within its own frame, but when a person moves
between cameras, that track is lost and a new one starts. IEP3 links those
fragments using spatial voting (floor-plane overlap) and ReID appearance matching
(cosine similarity on resnet50_msmt17 embeddings) to produce one continuous
identity per person across the entire store.

## 2. Input contract

- Reads from: `stream:iep2:batch_complete` on server Redis
- Consumer group: `iep3-{store_id}`
- **XACK-before-processing**: IEP3 ACKs each message immediately on receipt
  (before the reconciliation transaction). See
  `docs/decisions/ADR-001-xack-before-processing.md` for the full rationale.
  The PEL is always empty after a clean run; orphan sweep handles any partial
  state from a previous crash.
- `BatchCoordinator` waits for all expected cameras in a store to emit
  `batch_complete` for the same `window_id` before proceeding. If any camera
  is late beyond `COORDINATOR_TIMEOUT_S` (default 120 s), the batch proceeds
  with the cameras that responded.

## 3. Processing algorithm

Each completed window runs as a single asyncpg transaction:

1. **BatchReader** — load `local_centroids` (packed 2048-dim embeddings) for all
   `local_id`s seen in this window across all cameras.
2. **SpatialVoter** — for each pair `(local_id_A from cam_A, local_id_B from cam_B)`:
   counts windows where both were co-visible within `VOTE_DISTANCE_THRESHOLD_M`
   (default 1.0 m) and `TEMPORAL_TOLERANCE_MS` (default 150 ms). A match is
   confirmed when `votes ≥ MIN_VOTES` (default 10) and
   `vote_rate ≥ MIN_VOTE_RATE` (default 0.60).
3. **ReidMatcher (appearance fallback)** — fires only when the winner's vote rate
   margin is below `AMBIGUITY_MARGIN` (default 0.15). Computes median cosine
   similarity on packed 2048-dim embeddings; pair confirmed if ≥
   `REID_FALLBACK_THRESHOLD` (default 0.55).
   Unmatched `local_id`s get a new `global_id`.
4. **PositionSelector** — for each `global_id`, pick the canonical floor position
   for this window: scores each contributing `(local_id, camera)` by
   `POSITION_WEIGHT_AREA × bbox_area_score + POSITION_WEIGHT_CONF × confidence_score`
   (defaults 0.7 / 0.3). Writes one `global_tracking_history` row per `global_id`.
5. **StateManager** — runs ACTIVE → LOST → EXITED transitions (see §4).

## 4. Global identity state machine

```
[NEW] ──► ACTIVE ──► LOST ──► EXITED
                 └──────────► EXITED (grace timeout)
LOST ──► ACTIVE (re-detection in a later window)
```

**Transition conditions (from `state.py` and `repository.py`):**

- **NEW → ACTIVE:** `global_id` created by ReidMatcher when a `local_id` is
  unmatched to any existing `global_id`.
- **ACTIVE → LOST:** No active `global_local_mapping` row was seen in this window
  (i.e. the person had no position written since `window_start_ms`). The
  `lost_since_ts` is set to `window_end_ms`.
- **LOST → ACTIVE:** ReidMatcher finds a cosine match above threshold for a
  `local_id` in a later window. The existing `global_id` is reused (the person
  re-entered the scene). `lost_since_ts` is cleared.
- **LOST → EXITED:** `(window_end_ms - lost_since_ts) > grace_seconds × 1000`
  (default `grace_seconds = 300`). A `global_id` that was just marked LOST this
  batch will never exit in the same batch (the gap is 0 ms < grace).
- **EXITED:** Terminal. Mappings deactivated, `local_centroids` for linked
  `local_id`s deleted. A new appearance of the same person in a later window
  creates a fresh `global_id`.

## 5. Output contract

### Written to PostgreSQL (one asyncpg transaction per window)

| Table | Written |
|---|---|
| `global_identities` | Upserted per `global_id` — state, `last_seen_ts`, `last_floor_x/y`, `exit_zone_id` |
| `global_local_mapping` | INSERT on new link; deactivated on EXITED |
| `global_embeddings` | Per-camera centroid updated using EMA (`CENTROID_EMA_ALPHA = 0.3`) |
| `global_tracking_history` | One row per `global_id` per batch — canonical floor position, `source_camera`, `selection_score` |

## 6. Error behavior and crash safety

| Error condition | Behavior |
|---|---|
| Crash mid-batch | XACK-before-processing: no message is re-delivered. The partial DB transaction rolls back. Orphan sweep on next startup cleans any partial `global_identities` rows from the crashed run. |
| PostgreSQL transaction fails | asyncpg rolls back. The window's output is lost. IEP3 logs the error and continues to the next batch. |
| One camera never sends `batch_complete` | `BatchCoordinator` times out after `COORDINATOR_TIMEOUT_S` (default 120 s) and proceeds with the available cameras. |
| Cosine score below threshold for all candidates | New `global_id` created for the unmatched `local_id`. |
| Expected camera count changes (camera added/removed) | IEP3 re-queries the DB every `EXPECTED_CAMERAS_REFRESH_BATCHES` (default 10) batches. |

## 7. Configuration (env)

| Var | Default | Description |
|---|---|---|
| `STORE_ID` | required | one IEP3 instance per store |
| `WINDOW_SECONDS` | required | must match IEP1/IEP2 |
| `DATABASE_URL_SERVER` | required | `postgresql://…` (no `+asyncpg` prefix) |
| `SERVER_REDIS_URL` | `redis://redis:6379/0` | reads `batch_complete` stream |
| `VOTE_DISTANCE_THRESHOLD_M` | `1.0` | max floor distance (m) for a co-visible vote |
| `MIN_VOTE_RATE` | `0.6` | min votes/co-visible windows to confirm |
| `MIN_VOTES` | `10` | min raw vote count before any match is trusted |
| `TEMPORAL_TOLERANCE_MS` | `150` | max timestamp gap (ms) for co-visibility |
| `AMBIGUITY_MARGIN` | `0.15` | vote-rate gap below which ReID appearance fires |
| `REID_FALLBACK_THRESHOLD` | `0.55` | median cosine to confirm appearance match |
| `GRACE_SECONDS` | `300.0` | LOST → EXITED grace period |
| `EMBEDDING_DIM` | `2048` | ReID embedding dimension |
| `CENTROID_EMA_ALPHA` | `0.3` | EMA weight for embedding updates |
| `COORDINATOR_TIMEOUT_S` | `120.0` | partial-batch timeout |
| `POSITION_WEIGHT_AREA` | `0.7` | canonical position: bbox area weight |
| `POSITION_WEIGHT_CONF` | `0.3` | canonical position: detection confidence weight |
| `EXPECTED_CAMERAS_REFRESH_BATCHES` | `10` | how often to re-query DB for camera count |
| `ORPHAN_SWEEP_INTERVAL_BATCHES` | `50` | how often to run orphan sweep |

## 8. Independence evidence

- Separate Docker image: `iep3_reconciliation`.
- Daemon process — no HTTP port, no shared memory with IEP2.
- Communicates only via Redis stream (reads) and PostgreSQL (writes).
- Can be restarted independently — XACK model and orphan sweep guarantee
  consistency; no coordination with IEP2 is needed on restart.

## 9. Tests

```bash
# Unit tests — no DB, no Redis
pytest tests/unit/iep3/ -v
# 25 tests: gate (8), matcher (6), selector (5), state (6), camera_graph (N)

# Integration test — 3-camera reconciliation scenario (Postgres only)
pytest tests/e2e/test_iep3_reconciler.py -v -s
```
