# RetailVision — IEP2 + IEP3 Subsystem Architecture

> Technical reference for the vision (IEP2) and cross-camera reconciliation (IEP3)
> subsystems. Audience: the engineering team continuing this work. This document
> describes **what exists today**, why it is shaped this way, the role of every
> module, how to run and test it, and how to take it to production.
>
> Status: built across milestones M1–M6; full suite **100 passed** (unit +
> integration/e2e). The implementation lives in `common/`, `services/iep2_vision/`,
> `services/iep3_reconciliation/`, and `tools/`.

---

## 1. Overview & scope

RetailVision tracks shoppers across a store's cameras and produces a single
store-wide position track per person. The pipeline is decomposed into numbered
**IEP** (Inference / Edge Processing) stages:

| Stage | Role | Form |
|---|---|---|
| **IEP1** ingestion | (placeholder) ingest camera frames | FastAPI stub, port 8001 |
| **IEP2** vision | per-camera: detect → track → **Local ID** → PostgreSQL | CLI worker, one process per camera |
| **IEP3** reconciliation | cross-camera: Local ID → **Global ID** → canonical global track | single-instance, batch-triggered worker |
| **IEP4** alerts | (placeholder) rules/alerts | FastAPI stub, port 8004 |
| **IEP5** analytics | (placeholder) analytics | FastAPI stub, port 8005 |
| **IEP6** agent | (placeholder) LLM agent | FastAPI stub, port 8006 |
| **EEP** | API gateway / config / onboarding (existing) | FastAPI, port 8000 |

This document covers **IEP2** and **IEP3** (the only fully-implemented inference
stages) plus the shared `common/` package and the `tools/` orchestrator/demo.

**Scope boundary.** IEP2 currently reads a **video file** directly (testing/
bring-up mode). The seam for live ingestion from IEP1 already exists (see §3,
`SampledFrame`). IEP3 reads only IEP2's PostgreSQL output — the two services
never call each other directly; they are decoupled through the database plus a
`batch_complete` event.

**EEP relationship.** In production, the EEP service owns camera lifecycle, the
config state machine, and orchestration. For bring-up/demo/tests we ship a
lightweight stand-in: `tools/orchestrator.py`. It launches N IEP2 runtimes + the
IEP3 reconciler in one process. It is deliberately minimal; production replaces
it with EEP.

---

## 2. Repository layout

```
retail-edge/
├── common/                       # Shared package imported by BOTH services + tools
│   ├── config.py                 # pydantic-settings Settings + get_settings()
│   ├── logging_conf.py           # structured logging
│   ├── errors.py                 # exception hierarchy
│   ├── db/
│   │   ├── engine.py             # async engine + session_scope()
│   │   └── migrate.py            # idempotent create_all one-shot (the "migrate" job)
│   ├── models/                   # SQLAlchemy ORM (own Base) — mirror of schema.sql Domain 9
│   │   ├── base.py
│   │   ├── iep2_tables.py        # tracking_history, local_embeddings, local_centroids
│   │   ├── iep3_tables.py        # global_identities, global_local_mapping, global_embeddings, global_tracking_history
│   │   └── shared_tables.py      # camera_calibrations (demo/seed)
│   ├── contracts/                # pure dataclasses (no SQLAlchemy): geometry, detection, identity
│   └── utils/                    # embeddings (serialize/normalize/cosine), time, jsonio
│
├── services/
│   ├── eep/                      # existing API gateway; OWNS services/eep/schema.sql
│   │   └── schema.sql            # authoritative DDL; "Domain 9" = the 8 IEP2/IEP3 tables
│   ├── iep1_ingestion/           # placeholder
│   ├── iep2_vision/app/          # vision + identity + persistence + ingest + runtime + CLI
│   ├── iep3_reconciliation/app/  # reader + reid + selection + state + coordinator + CLI
│   ├── iep4_alerts/ iep5_analytics/ iep6_agent/   # placeholders
│
├── tools/
│   ├── orchestrator.py           # EEP stand-in: N IEP2 runtimes + IEP3 in one process
│   ├── seed_calibration.py       # writes demo camera_calibrations rows
│   ├── demo/{colors,review_page,render}.py        # annotated video + synced HTML review
│   └── Dockerfile                # orchestrator/job image (common + both services + tools)
│
├── tests/                        # unit + integration + e2e (see §11)
├── infra/prometheus.yml          # scrape config
├── docker-compose.yml            # full stack (infra + EEP + IEPs + monitoring + pipeline profile)
└── pyproject.toml                # pytest (asyncio_mode=auto), black/ruff (line 120)
```

> **Naming constraint (hard requirement).** The two inference packages and all
> service dirs use **underscores** (`iep2_vision`, `iep3_reconciliation`, …), not
> hyphens. IEP2/IEP3 import across services by package path
> (`from services.iep2_vision.app…`), and **Python cannot import a hyphenated
> package name**. A hyphenated dir makes the whole subsystem non-importable. Do
> not rename these to hyphens.

**Import roots.** The repo root is on `sys.path` (root `conftest.py` +
`pyproject.toml`). Code imports `from common.…` and
`from services.iep2_vision.app.…` / `from services.iep3_reconciliation.app.…`.

---

## 3. End-to-end architecture & data flow

```
                         ┌──────────────── IEP2 (one process PER camera) ────────────────┐
 video file ─▶ VideoFrameSource ─▶ Batcher ─▶ VisionPipeline ─▶ LocalIdentityManager ─▶ PersistencePort
 (or IEP1     (sample @ fps,      (group into  (detect→track→   (Track ID → Local ID;     │
  stream)      epoch-ms ts)        N-frame      preprocess→      pools, ReID, gallery)     │
                                   batches)     project)                                   ▼
                                                                          PostgreSQL: tracking_history,
                                                                          local_embeddings, local_centroids
                                                              end of batch │ emit batch_complete
                                                                           ▼
                                            Redis stream  ── OR ──  in-process emitter (orchestrator)
                                                                           ▼
                         ┌──────────────── IEP3 (single instance) ────────────────────────┐
                         BatchCoordinator (wait for ALL cameras' batch N) ─▶ Reconciler.process_batch:
                           reader.read_window  ─▶  P1 ReidMatcher (Local→Global, cross-cam)
                                               ─▶  P2 PositionSelector (best source per Global)
                                               ─▶  StateManager (ACTIVE→LOST→EXITED)
                                                                           ▼
                                              PostgreSQL: global_identities, global_local_mapping,
                                                          global_embeddings, global_tracking_history
```

**Batch / window model.** IEP2 samples each video at `sample_rate_fps` and groups
samples into fixed batches of `batch_window_seconds * sample_rate_fps` frames
(`Batcher`). Each sample carries a synthetic **epoch-ms timestamp**
(`start_epoch_ms + offset`), so the whole pipeline operates in one time domain
regardless of source. The tracker is **continuous across batch boundaries** — the
batcher only marks where to flush persistence and emit `batch_complete`. A batch's
`(window_start_ms, window_end_ms)` is `(frames[0].ts, frames[-1].ts)`.

**Cross-service decoupling.** IEP2 writes rows and emits a `batch_complete` event
carrying `{store_id, camera_id, batch_number, window_start_ms, window_end_ms}`.
IEP3's `BatchCoordinator` waits until **every** registered camera has reported the
same `batch_number`, then triggers `Reconciler.process_batch(batch, window)`,
which reads that window from `tracking_history`/`local_centroids` and writes the
global tables. Two transports for the event:
- **Redis stream** `stream:iep2:batch_complete` (distributed deployment).
- **In-process emitter** (`tools/orchestrator._InProcessEmitter`) calling
  `coordinator.note(...)` directly — no Redis needed for orchestrated/test runs.

**IEP1 streaming seam.** `services/iep2_vision/app/ingest/video_source.py` is the
**only** module that changes when live ingestion arrives. Swapping
`VideoFrameSource` for a `RedisStreamFrameSource` that yields the same
`SampledFrame(frame, timestamp_ms, frame_index)` leaves M2/M3 logic untouched.

---

## 4. Key decisions & rationale

| Decision | Why |
|---|---|
| **Shared `common/` package + importable underscore packages** | One source of truth for config, DB layer, ORM, contracts, utils; the orchestrator and e2e tests import both services in one process. Requires underscores (Python packages). |
| **Extend `schema.sql` + ORM models, no Alembic** | The repo had no migration tool; EEP applies `schema.sql` at Postgres init + `create_all`. The 8 new tables ("Domain 9") were appended to `services/eep/schema.sql` and mirrored as ORM models in `common/models/`. `common/db/migrate.py` provides an **idempotent** `create_all` one-shot for existing volumes (initdb only runs on a *fresh* volume). |
| **Unprefixed pydantic config** | EEP and `docker-compose.yml` already use `DATABASE_URL`/`REDIS_URL` with no prefix. `common/config.Settings` reads the same names (no `RV_` prefix) so the subsystem coexists in one `.env`. |
| **Calibration: production adapter + demo table** | Production reads the existing EEP `calibrations.homography_matrix` + `zones.points` via `load_calibration_from_eep`. The demo/e2e path uses a flat `camera_calibrations` table seeded by `tools/seed_calibration.py` and read by `load_calibration`. |
| **CPU/no-weights fallbacks** | `IouTracker` (dependency-free motion tracker) and `DescriptorEmbedder` (512-dim HSV-grid) let the whole pipeline + tests run on CPU with no GPU/weights/boxmot. Production backends (`bytetrack`/`botsort`, `osnet`) are selected by config. |
| **`PersistencePort` sync-buffer / async-DB split** | Position writes are buffered (sync, flushed every `position_flush_seconds`); embedding/centroid writes hit the DB (async). `LocalIdentityManager.process_frame` is **async** and takes an explicit `timestamp_ms` (resolves M3's `det....` placeholder without mutating the M2 `FrameDetection` contract). `on_batch_boundary` is sync. |
| **In-process orchestrator emitter** | Lets the orchestrator/tests exercise the full IEP2→IEP3 chain with **only Postgres** (no Redis). The Redis path remains for distributed deployment. |
| **Matcher `create_global` sets `last_floor` + `flush()`** | Makes same-batch multi-camera linking correct: a Global ID created for the first camera's observation is immediately visible (with a position) to later observations in the same batch, so the cross-camera gate and ReID can link them. |

---

## 5. Data model ("Domain 9")

DDL in `services/eep/schema.sql`; ORM mirror in `common/models/` (own `Base` so
tests can `create_all`). **Ownership invariant:** IEP2 writes `tracking_history`,
`local_embeddings`, `local_centroids`; IEP3 reads `tracking_history` +
`local_centroids` **read-only** and owns the four `global_*` tables.

**IEP2 tables**
- `tracking_history(id PK, local_id UUID, camera_id, timestamp_ms, floor_x, floor_y, zone_id, bbox_confidence, bbox_area)` — one row per confirmed position update (2 s buffered). Indexes on `(local_id, timestamp_ms)`, `(timestamp_ms)`, `(camera_id, timestamp_ms)`.
- `local_embeddings(local_id, captured_ts) PK, camera_id, embedding BYTEA, yolo_confidence, is_init` — persistent gallery store for crash recovery/audit. **`embedding` is `float32[D].tobytes()`** — self-describing: D (the active model dim) is recovered from the blob length, so IEP3 reads it without knowing the model.
- `local_centroids(local_id PK, camera_id, centroid BYTEA, updated_at_batch)` — current centroid per Local ID; the primary ReID interface IEP3 reads. UPSERTed on every gallery change.

**IEP3 tables**
- `global_identities(global_id PK, store_id, first_seen_ts, last_seen_ts, state, lost_since_batch, last_floor_x, last_floor_y)` — `CHECK state IN ('active','lost','exited')` (`state_valid`). `last_floor_x/y` cache the last canonical position so the cross-camera gate is a single-row lookup.
- `global_local_mapping(id PK, global_id FK, camera_id, local_id, is_active, linked_at_batch, last_seen_batch, unlinked_at_batch)` — Local↔Global links with full history (old links kept `is_active=false`). **Partial unique index `uq_glm_global_camera_active` on `(global_id, camera_id) WHERE is_active = true`** enforces "one active Local ID per camera per Global ID".
- `global_embeddings(global_id, camera_id) PK, centroid BYTEA, updated_at_batch` — per-camera centroid for cross-camera matching.
- `global_tracking_history(id PK, global_id FK, store_id, batch_number, timestamp_ms, floor_x, floor_y, zone_id, source_camera, source_local_id, selection_score)` — **canonical store-wide track: exactly one row per Global ID per batch.** This is the downstream product (alerts/analytics/dashboards).

**Demo table**
- `camera_calibrations(cam_id PK, store_id, homography DOUBLE PRECISION[], zone_polygons JSONB)` — flat demo calibration; `homography` is a 9-element row-major 3×3 (length validated in app code, not the column).

---

## 6. Component reference (modules + key functions)

### 6.1 `common/`

- **`config.py`** — `class Settings(BaseSettings)` (env_file=`.env`, `extra="ignore"`, **no prefix**) and `get_settings() -> Settings` (process singleton). Holds every tunable (see §8).
- **`logging_conf.py`** — `configure_logging(service_name)`; JSON when `log_json`, else plain.
- **`errors.py`** — `RetailVisionError` base + `ConfigurationError`, `CalibrationError`, `EmbeddingError`, `PersistenceError`.
- **`db/engine.py`** — `get_engine()` (lazy async engine, `pool_pre_ping`, pool sized by config), `get_session_factory()`, `@asynccontextmanager session_scope()` (commit on success / rollback on exception), `dispose_engine()` (also clears the cached factory).
- **`db/migrate.py`** — `async apply_schema()` runs `Base.metadata.create_all` (checkfirst → idempotent); `main()` for `python -m common.db.migrate`. This is the compose `migrate` one-shot.
- **`models/base.py`** — `Base(DeclarativeBase)` with a fixed naming convention (deterministic constraint/index names).
- **`models/iep2_tables.py`**, **`models/iep3_tables.py`**, **`models/shared_tables.py`** — the ORM classes from §5. `iep3_tables` declares the partial unique index via `Index(..., unique=True, postgresql_where=(is_active == True))` and the `state` `CheckConstraint`.
- **`contracts/geometry.py`** — `BBox(x1,y1,x2,y2)` with `.width/.height/.area/.foot_point` (center-bottom, the floor-projection anchor); `FloorPosition(x,y)` (meters).
- **`contracts/detection.py`** — `Detection(bbox, confidence)`, `TrackedDetection(track_id, bbox, confidence)`.
- **`contracts/identity.py`** — `TrackState`, `GlobalState` enums; `BatchCompleteEvent(store_id, camera_id, batch_number, window_start_ms, window_end_ms)`.
- **`utils/embeddings.py`** — `serialize_embedding(vec)->bytes`, `deserialize_embedding(blob, dim=None)->np.ndarray` (self-describing: infers dim from byte length; pass `dim` only as an optional mismatch guard), `l2_normalize(vec, eps)`, `cosine_similarity(a,b)`.
- **`utils/time.py`** — `now_ms()`, `ms_to_seconds(ms)`.
- **`utils/jsonio.py`** — `write_json_atomic(path, data)` (temp + rename), `read_json(path)`.

### 6.2 `services/iep2_vision/app/` (vision + identity + persistence)

**Vision plugins (`vision/`)** — each family is a `Protocol` + implementations + factory, selected by config:
- **`detector.py`** — `Detector` protocol (`detect(frame)->list[Detection]`, person-class only, conf-filtered); `Yolo11PersonDetector`, `RtDetrPersonDetector` (lazy `ultralytics` import); `create_detector(backend, **kw)`. `PERSON_CLASS = 0`.
- **`tracker.py`** — `Tracker` protocol (`update(detections, frame)->TrackerOutput`); `TrackerOutput(confirmed, new, lost_track_ids)`; `IouTracker(min_hits,max_age,track_thresh,match_thresh)` (dependency-free greedy-IoU; confirms after `min_hits`, drops after `max_age`, reports a confirmed track `lost` exactly once); `ByteTrackTracker`/`BotSortTracker` (lazy boxmot); `create_tracker(backend, **kw)`. **Invariant:** `update([])` must still advance state and can emit lost tracks — callers never short-circuit on empty detections.
- **`reid.py`** — `ReIDModel` protocol (`embedding_dim`, `extract(crop)`, `batch_extract`); `DescriptorEmbedder` (512-dim 4×4 HSV grid, deterministic, CPU-only); `OSNetEmbedder` fallback chain boxmot → torchreid → torchvision ResNet50 → descriptor, with `embedding_dim` read from the loaded backend; `create_reid_model(backend, **kw)`. `DESCRIPTOR_DIM = 512`.
- **`projection.py`** — `FloorProjector(homography_3x3, zone_polygons, store_bounds)`: `project(bbox)->FloorPosition|None` (foot-point homography; returns `None` behind camera or out of bounds), `zone_of(pos)->str|None` (Shapely point-in-polygon).
- **`preprocess.py`** — `suppress_duplicates(dets, iou_thresh, containment_thresh)` and `filter_low_quality(dets, frame_shape, min_height_ratio, min_aspect_ratio)`; each returns `(kept, count)`.
- **`pipeline.py`** — `FrameDetection(track_id, bbox, confidence, floor_pos, zone_id)`; `VisionPipeline(detector, tracker, projector, settings).process_frame(frame) -> (list[FrameDetection], TrackerOutput, metrics)`. Order: detect → track → suppress dup → filter quality → project. The embedder is **not** called here (M3 decides when).

**Calibration** — `calibration.py`: `load_calibration(row)->(H, zones, bounds)` (demo `CameraCalibration` row; validates 9-element homography); `load_calibration_from_eep(homography_matrix, zone_rows, cam_id)` (production adapter over EEP tables); `_compute_store_bounds(zones)` (open-plane fallback when no zones).

**Identity (`identity/`)** — turns ephemeral Track IDs into stable Local IDs:
- **`pools.py`** — `TempPosition`, `ActiveTrack`, `PendingTrack` (with parallel `embeddings`/`embedding_ts`), `LostEntry`; `IdentityPools` holding `active` (by track_id), `pending` (by track_id), `lost` (by local_id) dicts; `prune_lost(current_batch)` (the **only** pruning path; called once per batch boundary).
- **`gallery.py`** — `EmbeddingGallery(max_size, ema_alpha)`: `add(vec)` (EMA below capacity; novelty-based replace at capacity — replace the most-redundant entry only if the newcomer is more novel, then recompute centroid from scratch); `snapshot_centroid()`.
- **`gates.py`** — `spatial_temporal_gate(new_x,new_y,new_ts, last_x,last_y,last_ts, max_speed_mps)` (walking-speed plausibility; `elapsed<=0` accepts, no div-by-zero).
- **`resolution.py`** — `resolve(pending, pools, settings) -> Resolution(local_id, matched, matched_lost_local_id)`: SpatialCheck (gate vs Lost pool) → ReIDMatch (mean pending embedding vs survivor centroids) → Validate (`reid_match_threshold`). Pure; does not mutate pools.
- **`manager.py`** — `LocalIdentityManager(camera_id, embedder, persistence, settings)`. `async process_frame(frame, frame_dets, tracker_out, timestamp_ms)` processes in order **lost → new → confirmed → pending**. Fast path (`_assign_confirmed`, no Lost candidates) creates a Local ID and bootstraps one init embedding so the centroid is never `None`. Pending path collects `init_embeddings_count` embeddings then `resolve`s. `_on_confirmed` updates the active track, buffers a position, and quality-gated-samples embeddings every `sample_interval_frames`. `_commit` writes init embeddings (each with a distinct `captured_ts`), upserts the centroid, and flushes buffered temp positions under the resolved Local ID. `on_batch_boundary(batch_number)` advances batch number, prunes the Lost pool, returns metrics.

**Persistence (`persistence/`)**
- **`ports.py`** — `PersistencePort` protocol. Sync (buffered): `append_position(...)`, `flush_temp_positions(local_id, camera_id, positions)`. Async (DB): `write_embedding(local_id, camera_id, captured_ts, embedding, yolo_confidence, is_init)`, `upsert_centroid(local_id, camera_id, centroid, batch_number)`.
- **`postgres.py`** — `PostgresPersistence(settings)` implements the port: buffers positions, `async maybe_flush(force=False)` bulk-inserts every `position_flush_seconds` or on force; `write_embedding` uses `ON CONFLICT (local_id, captured_ts) DO NOTHING`; `upsert_centroid` uses `ON CONFLICT (local_id) DO UPDATE`.

**Ingest (`ingest/`)**
- **`video_source.py`** — `SampledFrame(frame, timestamp_ms, frame_index)`; `VideoFrameSource(video_path, target_fps, start_epoch_ms)` samples a video at `target_fps` (capped at source fps), assigning epoch-ms timestamps. **The IEP1-streaming seam.**
- **`batcher.py`** — `Batcher(source, batch_window_seconds, target_fps)` yields `(batch_number, list[SampledFrame])`, including a final partial batch.

**Service plumbing**
- **`recovery.py`** — `async reconstruct_lost_pool(camera_id, current_batch, settings) -> {local_id: LostEntry}` — warm restart: latest position per Local ID from `tracking_history` within TTL, centroid from `local_centroids`, gallery from `local_embeddings`.
- **`events.py`** — `BatchEventEmitter(redis_url=None)`; `STREAM = "stream:iep2:batch_complete"`; `async emit(...)` `XADD`s; redis imported lazily (optional for non-event paths).
- **`metrics.py`** — private `REGISTRY`; `frame_latency`, `detections_per_frame`, `reid_resolutions`, `active_tracks`, `lost_pool_size`, **`detection_confidence`** (ML signal); `start_metrics_server(port)`.
- **`runtime.py`** — `Iep2Runtime(store_id, camera_id, settings)`. `async setup(calibration_row, *, detector=None, tracker=None, embedder=None, persistence=None, events=None, warm_restart=True)` builds the pipeline from config unless components are injected (**DI for tests/CPU path**); records the active model's `embedding_dim` on the runtime (does **not** mutate the shared settings — embeddings are self-describing); warm-restarts the Lost pool. `async run(video_path, start_epoch_ms)` drives the batch loop (per frame: pipeline → manager → `maybe_flush` → metrics; per batch: force-flush → `on_batch_boundary` → gauges → emit).
- **`main.py`** — CLI worker: `--store-id --camera-id --video --start-ms`; loads the demo `CameraCalibration` row; starts metrics server if `METRICS_PORT` set; runs one camera.

### 6.3 `services/iep3_reconciliation/app/`

- **`repository.py`** — `Iep3Repository(settings)`, the **single DB layer**. Reads: `load_local_centroid`, `active_mapping_for`, `candidate_globals(store_id, states)` (returns `[(GlobalIdentity, {camera_id: centroid})]`, with `last_floor_x/y` riding on the ORM object). Writes: `create_global(..., last_floor_x, last_floor_y)` (sets position + `flush()`), `link` (deactivates prior active link for the camera, inserts new active), `touch_link`, `upsert_global_centroid` (`ON CONFLICT (global_id, camera_id)`), `reactivate_if_lost`, `update_global_last_position`, `write_global_position`.
- **`reader.py`** — `LocalObservation` dataclass; `BatchReader.read_window(start_ms, end_ms)` aggregates `tracking_history` per `(local_id, camera_id)` → last/first position+ts, best confidence/area. Read-only, own session.
- **`reid/gates.py`** — `cross_camera_gate(...)` (same walking-speed filter as IEP2, on shared floor coords).
- **`reid/matcher.py`** — `ReidMatcher(repo, settings)`. **Process 1.** `link_new_locals(session, store_id, new_obs, batch)` sorts by `first_seen_ts` (handles simultaneous multi-camera). `_resolve_one` loads the new centroid, fetches active+lost candidates, **skips candidates already mapping this camera** (cross-camera only), applies the gate (accepts when a candidate has no known position yet), scores cosine vs the representative (mean) centroid, and either creates a new Global ID or links to the best ≥ `reid_match_threshold` (reactivating if it was lost, updating last position). Emits `global_links`/`match_similarity` metrics.
- **`selection.py`** — `selection_score(bbox_area, confidence, frame_pixels, w_area, w_conf)`; `PositionSelector(repo, settings, frame_pixels_by_camera)`. **Process 2.** `write_canonical_positions(...)` joins `tracking_history`↔active `global_local_mapping` for the window, keeps the highest-scoring report per Global ID, writes **one** `global_tracking_history` row and updates the Global ID's last position.
- **`state.py`** — `StateManager(repo, settings).run_cleanup(session, batch)`: ACTIVE→LOST when no active link was seen this batch; LOST→EXITED after `global_grace_batches`; deactivates exited mappings. (LOST→ACTIVE re-entry is the matcher's job.)
- **`reconciler.py`** — `Reconciler(store_id, repo, settings, frame_px).process_batch(batch_number, window)`: read → classify (touch existing active maps vs new) → P1 → P2 → cleanup, **all writes in one transaction** (atomic batch). Observes `reconcile_latency`, increments `positions_written`.
- **`coordinator.py`** — `BatchCoordinator(expected_cameras, on_ready, timeout_seconds=None, redis_url=None, clock=monotonic)`. Pure testable core: `async note(batch, camera, window)->bool` (fires `on_ready` when all expected cameras reported), `async check_timeouts()->list[int]` (partial reconcile for stale batches — partial-camera-failure handling), `async drain()->list[int]` (fire all still-tracked batches; used by the orchestrator for trailing/uneven batches). `async run()` is the thin Redis-stream adapter (`STREAM`, `GROUP`, `XREADGROUP`/`XACK`).
- **`metrics.py`** — private `REGISTRY`; `reconcile_latency`, `global_links{outcome}`, `active_globals`, `positions_written`, **`match_similarity`** (ML signal); `start_metrics_server(port)`.
- **`main.py`** — `async run_service(store_id, cameras, frame_px, timeout_seconds=None)` wires repo + reconciler + coordinator and runs the Redis loop; starts metrics if `METRICS_PORT` set; CLI parses `--store-id --cameras --frame-px`.

### 6.4 `tools/`

- **`orchestrator.py`** — `RunPlan(store_id, cameras: {cam: video}, frame_px: {cam: px})`; `_InProcessEmitter(coordinator)` (`emit(...)` → `coordinator.note(...)`); `async run(plan, calibrations, *, overrides=None, settings=None, start_ms=None)` builds the IEP3 reconciler + coordinator, launches one `Iep2Runtime` per camera via `asyncio.gather` (each wired to the in-process emitter; `overrides[cam]` injects detector/tracker/embedder for tests), then `coordinator.drain()`; `async load_calibrations(cam_ids)` reads demo `CameraCalibration` rows; `_main()` is the CLI.
- **`seed_calibration.py`** — `async seed_calibration(store_id, cam_ids, *, homography=None, zone_polygons=None)` UPSERTs `camera_calibrations`; `IDENTITY_HOMOGRAPHY`, `DEFAULT_ZONES`; CLI `--store --cameras` (store name hashed to a uuid5).
- **`demo/colors.py`** — `global_id_rgb/global_id_bgr/global_id_hex(global_id)` — deterministic colour per Global ID (stable across camera panels).
- **`demo/review_page.py`** — `build_review_html(cameras, metrics, global_ids)` / `render_review_page(path, …)` — self-contained synchronized multi-camera HTML page + metrics table + Global-ID legend (vanilla JS `requestAnimationFrame` sync).
- **`demo/render.py`** — `async render_camera(video_path, camera_id, output_path, start_ms, sample_fps)` re-reads a video and draws each detection's **Global ID** (joined via `global_local_mapping`) at its floor position projected back to pixels with the **inverse homography** (`_load_homography`, `_load_overlays`, `_floor_to_pixel`). No stored pixel bbox; no re-running detection.
- **`Dockerfile`** — orchestrator/job image: CPU torch + vision requirements + `common` + both services + `tools`.

---

## 7. Invariants & algorithms

**IEP2 identity lifecycle.** Three pools: **Active** (confirmed Local IDs), **Pending**
(collecting `init_embeddings_count` embeddings before ReID), **Lost** (recently
disappeared, ReID candidates with a TTL of `lost_pool_ttl_batches`). New track with
empty Lost pool → immediate Local ID (fast path). New track with a non-empty Lost
pool → Pending → on reaching the init count, `resolve` either re-identifies a Lost
Local ID (re-uses it, flushes buffered temp positions under it) or mints a new one.
**Scenario 1** (occlusion → re-ID keeps the same Local ID) is the canonical test.
Lost-pool TTL is enforced **only** at batch boundaries (deterministic; never
per-frame). Init embeddings are not quality-gated; sampled embeddings are
(`yolo_confidence_gate`, `track_age_gate_frames`, `min_bbox_area_px`).

**IEP3 invariants (enforced + tested).** (1) One active Local ID per camera per
Global ID — partial unique index + `link` deactivates the prior active row. (2)
Cross-camera ReID only — the matcher skips candidates already mapping the same
camera. (3) New Local IDs processed in `first_seen_ts` order. (4) Exactly one
`global_tracking_history` row per Global ID per batch — the selector groups by
`global_id`. (5) IEP3 never writes IEP2 tables — the repository only reads
`local_centroids`/`tracking_history`.

**Selection score:** `w_area * (bbox_area / frame_pixels) + w_conf * confidence`
(defaults `0.7` / `0.3`). **Gates:** `distance / elapsed_s <= max_walking_speed_mps`
(accept when `elapsed_s <= 0`). **Gallery diversity:** farthest-first replacement
with from-scratch centroid recompute on replace (no EMA after a removal).

---

## 8. Configuration reference (`common/config.py`)

All fields are env-overridable (case-insensitive, no prefix). Selected fields:

| Field | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://retailvision:…@localhost:5432/retailvision` | async DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | batch_complete stream |
| `db_pool_size` / `db_max_overflow` | 10 / 20 | engine pool |
| `batch_window_seconds` | 60 | batch length |
| `embedding_dim` | 512 | advisory only — embeddings are self-describing; readers infer the dim from the bytes |
| `gallery_max_size` / `init_embeddings_count` / `sample_interval_frames` | 8 / 5 / 15 | gallery + sampling |
| `reid_match_threshold` | 0.75 | cosine threshold (IEP2 + IEP3) |
| `max_walking_speed_mps` | 1.5 | spatial gate |
| `centroid_ema_alpha` | 0.05 | gallery EMA |
| `yolo_confidence_gate` / `track_age_gate_frames` / `min_bbox_area_px` | 0.6 / 10 / 8192 | sample-embedding quality gates |
| `lost_pool_ttl_batches` / `global_grace_batches` | 5 / 5 | TTL / LOST→EXITED grace |
| `selection_weight_bbox_area` / `selection_weight_confidence` | 0.7 / 0.3 | Process 2 score |
| `position_flush_seconds` | 2.0 | persistence buffer flush |
| `detector_backend` / `detector_model` / `detector_confidence` / `detector_nms_iou` | yolo11 / yolo11x.pt / 0.55 / 0.7 | detector |
| `tracker_backend` | bytetrack | tracker (`iou` for CPU/test) |
| `reid_backend` / `reid_model` | osnet / osnet_x1_0 | ReID (`descriptor` for CPU/test) |
| `device` | None (auto cuda) | torch device |
| `duplicate_iou_threshold` / `duplicate_containment_threshold` | 0.65 / 0.78 | dup suppression |
| `min_detection_height_ratio` / `min_detection_aspect_ratio` | 0.12 / 1.15 | quality filter |
| `bytetrack_min_hits` / `_max_age` / `_track_thresh` / `_match_thresh` | 3 / 30 / 0.5 / 0.8 | tracker params |
| `sample_rate_fps` | 5.0 | video sampling |
| `log_level` / `log_json` | INFO / true | logging |

Other env: `METRICS_PORT` (start a `/metrics` server in a worker entrypoint).

---

## 9. Observability

Each inference service defines a **private** `prometheus_client.CollectorRegistry`
(no global-registry collisions) and a `start_metrics_server(port)` helper, called
from the worker entrypoints when `METRICS_PORT` is set.

- **IEP2:** `iep2_frame_processing_seconds`, `iep2_detections_per_frame`,
  `iep2_reid_resolutions_total`, `iep2_active_tracks`, `iep2_lost_pool_size`, and
  the ML signal `iep2_detection_confidence`.
- **IEP3:** `iep3_batch_reconcile_seconds`, `iep3_global_links_total{outcome}`,
  `iep3_active_global_ids`, `iep3_positions_written_total`, and the ML signal
  `iep3_cross_camera_similarity`.

`infra/prometheus.yml` scrapes jobs `iep2_vision` / `iep3_reconciliation`. Grafana
(compose, port 3001) consumes Prometheus (port 9090). See §13 for the CLI-worker
scraping caveat.

---

## 10. How to run

### Local (tests, no Docker)
```bash
pip install -r services/iep2_vision/requirements.txt     # vision + DB deps
pip install pytest pytest-asyncio                         # test runner

# Unit suite (CPU, no DB, no weights):
pytest tests/common tests/iep2 tests/iep3 tests/demo tests/pipeline

# Integration/e2e (needs Postgres):
docker run -d --name rv_pg -e POSTGRES_USER=rv -e POSTGRES_PASSWORD=rv \
  -e POSTGRES_DB=rvtest -p 5544:5432 postgres:15-alpine
DATABASE_URL=postgresql+asyncpg://rv:rv@localhost:5544/rvtest \
  RV_RUN_INTEGRATION=1 pytest tests
```

### Docker (full stack + pipeline)
```bash
# 1. Infra + schema. `migrate` is a one-shot that idempotently applies Domain 9
#    (needed because schema.sql initdb only runs on a FRESH postgres volume).
docker compose up -d --build postgres redis migrate

# 2. Build the pipeline images (profile-gated; not started by a plain `up`).
docker compose --profile pipeline build

# 3. Seed demo calibration + run the full IEP2→IEP3 chain (orchestrator job image
#    bundles common + both services + tools):
docker compose run --rm orchestrator python -m tools.seed_calibration \
  --store demo --cameras cam1,cam2
docker compose run --rm orchestrator python -m tools.orchestrator \
  --store-id 00000000-0000-0000-0000-000000000001 \
  --camera cam1=/app/testing-data/Test1/Camera1.mp4 \
  --camera cam2=/app/testing-data/Test1/Camera2.mp4
```
> The first real run **downloads the YOLO weights** (default `detector_backend=yolo11`)
> into the mounted model-cache volume (one-time). For a weight-free run set
> `TRACKER_BACKEND=iou` and `REID_BACKEND=descriptor` — note the production detector
> still needs `ultralytics` weights (there is no CPU stub detector outside tests).

**Per-camera worker (distributed, Redis path):**
`python -m services.iep2_vision.app.main --store-id … --camera-id cam1 --video … --start-ms …`
(one process per camera), with the IEP3 coordinator running `run_service(...)`.

---

## 11. Testing strategy

Test pyramid (`pyproject.toml` sets `asyncio_mode=auto`):
- **Unit** (always run, CPU, no DB/weights): `tests/common`, `tests/iep2/{vision,identity,ingest}`,
  `tests/iep3/{test_gates,test_selection_score,test_coordinator}`, `tests/demo`.
- **Integration** (gated by `RV_RUN_INTEGRATION=1` + a real Postgres): `tests/iep2/integration`,
  `tests/iep3/integration`, `tests/pipeline/integration`. Shared setup in
  `tests/integration_support.py` (`reset_settings_and_engine`, `prepare_db` = `create_all` +
  TRUNCATE); per-package `conftest.py` exposes the `pg` fixture.
- **e2e**: `tests/pipeline/integration/test_full_pipeline.py` — the headline 3-camera scenario
  through the orchestrator (Cam2+Cam3 → one Global ID, Cam1 separate, one canonical position per
  global); `test_iep2_to_iep3.py` (chain), `test_render.py` (annotated-video smoke),
  `test_seed_calibration.py`.

**Test doubles** (no real models/DB): `FakePersistence` + `LabelEmbedder` (`tests/iep2/identity/helpers.py`),
`StubDetector` + `FixedEmbedder` + `write_video` + `identity_calibration` (`tests/pipeline/integration/helpers.py`),
seed helpers (`tests/iep3/integration/seed.py`). Current status: **100 passed** (unit + integration).

---

## 12. Scaling & production path

- **Replace the orchestrator with EEP.** `tools/orchestrator.py` is a single-process stand-in. EEP
  manages camera lifecycle, retries, and the config state machine, launching IEP2 per camera and the
  IEP3 coordinator as long-lived services.
- **IEP2 scales horizontally by camera** — one process per camera, stateless except for in-memory
  pools that are warm-restarted from PostgreSQL (`recovery.reconstruct_lost_pool`). Add cameras = add
  processes.
- **IEP3 is single-instance, batch-triggered** (the reconciliation must serialize per store to keep
  Global IDs consistent). Scale by **store** (one IEP3 per store), not by replica.
- **Switch transport to Redis** for distributed deployment: IEP2 keeps using `BatchEventEmitter`;
  IEP3 runs `BatchCoordinator.run()` consuming `stream:iep2:batch_complete`. The in-process emitter is
  only for single-process orchestrated runs.
- **GPU**: set `device=cuda`; the OSNet/YOLO backends use it automatically. The orchestrator/worker
  Dockerfiles install CPU torch — override that layer for a GPU base image.
- **Swap models by config** (no code change): `detector_backend`, `tracker_backend`, `reid_backend`
  + model names. The embedding dimension follows the active ReID model automatically — stored
  embeddings are self-describing, so swapping to a different-dim model needs no config change and IEP3
  (which has no model) still deserializes correctly.
- **DB scaling**: the hot tables (`tracking_history`, `global_tracking_history`) already carry the
  needed indexes; partition them by time and add a retention job; consider read replicas for
  analytics consumers of `global_tracking_history`.
- **Resilience**: `BatchCoordinator(timeout_seconds=…)` triggers **partial reconciliation** if a
  camera never reports (crash) instead of stalling. Tune `batch_window_seconds` for the latency/
  accuracy trade-off.
- **Live ingestion**: implement `RedisStreamFrameSource` yielding `SampledFrame` and select it in the
  IEP2 entrypoint — M2/M3 are untouched.

---

## 13. Known gaps / tech debt

- **No Alembic.** `services/eep/schema.sql` only applies on a *fresh* Postgres volume (initdb). For
  existing volumes, the `migrate` one-shot (`common/db/migrate.py`, idempotent `create_all`) is the
  only thing that adds Domain 9 — it must run before the pipeline. A real migration tool is the
  long-term fix (schema changes beyond additive `create_all` are not handled).
- **`version_sync_events.iep1_ack..iep5_ack`** columns in the EEP schema were **not** remapped to the
  new IEP1–IEP6 numbering. Reconcile when wiring the config activation state machine.
- **Metrics on short-lived CLI workers** aren't scrapeable as-is — a per-run worker exits before
  Prometheus scrapes it. Use a Pushgateway, or run IEP2/IEP3 as long-lived services with a stable
  `/metrics` port, before relying on the dashboards.
- **`tools/demo/render.py`** draws Global-ID **markers** at the inverse-projected floor point, not
  pixel bounding boxes (no bbox is stored and detection is not re-run). Fine for the demo; for precise
  boxes, persist a demo-only pixel bbox or re-run detection in the render pass.
- **`IouTracker` / `DescriptorEmbedder`** are correctness-preserving **dev fallbacks**, not
  production-accurate. Production must use `bytetrack`/`botsort` + `osnet` with weights.
- **`embedding_dim` (resolved)** — embeddings are now **self-describing** (the float32 blob length
  encodes the dim), so `deserialize_embedding(blob)` infers it and no reader depends on config.
  `Iep2Runtime` no longer mutates the `Settings` singleton (it keeps the active dim on the runtime for
  reference only); IEP3 — which has no ReID model — deserializes exactly what IEP2 wrote. Pass a `dim`
  to `deserialize_embedding` only as an optional corruption/mismatch guard.
- **Reader/selection window is end-exclusive** (`timestamp_ms < window_end`), so a position at exactly
  `window_end` falls into the next batch. Intended across batches; only the final partial batch's last
  frame is affected.
- **Naming**: see §2 — the inference packages must stay underscored.

---

## 14. Glossary

- **Local ID** — per-camera stable identity (UUID) assigned by IEP2; survives short occlusions via the Lost pool.
- **Global ID** — store-wide identity (UUID) assigned by IEP3 by linking Local IDs across cameras.
- **Batch / window** — a fixed time slice (`batch_window_seconds`); `window = (first_ts, last_ts)` of its sampled frames; the unit of persistence flush, `batch_complete`, and reconciliation.
- **Zone** — a named floor polygon (entrance/checkout/aisle/…); a floor position is tagged with the zone containing it.
- **Centroid** — L2-normalized mean appearance embedding (per Local ID in `local_centroids`, per camera per Global ID in `global_embeddings`).
- **Gallery** — the bounded, diversity-managed set of embeddings backing a centroid.
- **Active / Pending / Lost pool** — IEP2 in-memory identity states (confirmed / collecting init embeddings / recently disappeared).
- **Homography / foot point** — 3×3 pixel↔floor projection; the bbox center-bottom is the floor-projection anchor.
- **Reconciliation** — IEP3's per-batch process: link Local→Global (Process 1), select the canonical position (Process 2), advance the Global ID state machine.
- **Canonical position** — the single best-source `global_tracking_history` row per Global ID per batch; the subsystem's downstream product.
```
