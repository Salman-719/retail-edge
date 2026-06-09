# Test Rewrite — Top-Level Plan (per-service vertical, accumulating E2E)

How we replace the outdated `tests/` tree. We iterate one service at a time, bottom-up, rewriting its
unit + integration tests, and each service adds its slice to a SINGLE end-to-end spine that grows as
we go — the automated analogue of the manual phases in
[docs/TESTING_GUIDE.md](../../../docs/TESTING_GUIDE.md). The plan is deliberately churn-tolerant:
non-architectural code edits are expected, so tests anchor on frozen seams, not internal signatures.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). Uses the harness layout from
[cross-cutting/04-qa-harness.md](../cross-cutting/04-qa-harness.md). The per-service robustness specs
already define acceptance tests; this plan is the order, the seams, and the E2E spine those tests
plug into.

---

## Why this shape

The current `tests/` tree is mostly stale (the user's word): it references files that do not exist
(CI runs `tests/unit/test_schemas.py`, absent), the strategy docs are TODO stubs, and the manual
guide still walks through removed concepts (TESTING_GUIDE §3.3 "Section Creation" — sections were
deleted, see [[project_sections_removed]]). Rewriting blind would just re-rot. Two principles fix
that:

1. **Bottom-up vertical slices.** Test a service fully (unit + its integration seams) before moving
   up the pipeline, so each integration test can consume the REAL output of the service below it,
   exactly as TESTING_GUIDE Phase 4 (edge) feeds Phase 5 (E2E). The pipeline order is the test order.
2. **Frozen seams, churnable units.** Code details will change in the coming days. Integration and
   E2E assert ONLY on the documented contracts between services (DB schema, Redis/ZMQ payload shapes,
   gRPC protos, EEP API response models). Those are stable. Unit tests cover internals and are
   rewritten freely whenever internals change — a unit test breaking is expected and cheap; an
   integration/E2E test breaking means a CONTRACT moved and must be reviewed.

## The frozen seams (the contract inventory — verify before writing seam tests)

These are the only things integration/E2E may assert on. Confirm each against the code at the time of
writing (they are the stable surface, but verify, do not assume):

- **DB schema** — `services/eep/schema.sql` + Alembic head. Table/column names, types, and the
  idempotency constraints (`ON CONFLICT` keys, `octet_length` checks). This is the strongest seam.
- **Redis streams** — `stream:iep1:{camera_id}` (IEP1→IEP2 manifest), `stream:iep2:batch_complete`
  (IEP2→IEP3), `stream:iep2:live:{camera_id}` (IEP2→live_bridge). Assert on field names + value
  shapes, not producer internals.
- **ZMQ / msgpack payloads** — yolo input/output (`request_id, camera_id, timestamp_ms, frame` →
  `detections[{bbox_xyxy, confidence}]`), reid input/output (`crop` → `embedding` bytes). These are
  the inference contract.
- **gRPC protos** — `proto/agent.proto`, `proto/iep1_control.proto`, health. Message shapes are the
  EEP↔edge and edge↔IEP1 seam.
- **EEP API** — the Pydantic `response_model` on each router endpoint. The API contract the frontend
  and E2E depend on.
- **tmpfs frame layout** — `/dev/shm/frames/{camera_id}/{ts}.jpg` + manifest `frames[i]` entries.

A change to any of these is a contract change (§"Contract-change protocol"); a change to anything else
is a code detail that may break only unit tests.

## Per-service iteration template (apply to each, in order)

For service S:
1. **Confirm S's seams.** List S's inbound and outbound contracts from the inventory above. Write them
   down in the service's test module docstring so a reader knows what is frozen.
2. **Rewrite unit tests** (`tests/unit/<S>/`). Each function/class in isolation, including null/empty/
   boundary inputs (Q1 requirement). Use the conftest `sys.path` shim pattern (per
   cross-cutting/04). These are allowed to churn with internals. Fakes for adjacent transports
   (the fake yolo/reid endpoint, fakeredis, monkeypatched DB).
3. **Write integration tests** (`tests/integration/<S>/`, marker `integration`). Drive S's INBOUND
   seam with a real adjacent payload and assert S's OUTBOUND seam. Prefer the real transport against a
   compose stack where cheap (DB, Redis); use a contract double where the real producer is heavy
   (GPU inference). The assertion target is the seam shape, never S's internal state.
4. **Extend the E2E spine.** Add S's checkpoint to the single growing E2E test (below). Do not write a
   new E2E per service — one spine, more assertions.
5. **Exit criterion.** S's unit tests green with no infra; S's integration tests green on the compose
   stack; the E2E spine reaches and asserts S's checkpoint.

## The order (bottom-up, pipeline order)

1. **Inference services (yolo-service, reid-service).** Unit: pre/post-processing, batch assembly,
   2048-dim assertion, the recv-deadline behavior. Integration: ZMQ roundtrip (a frame in → detection
   out; a crop in → 2048-dim embedding out) — TESTING_GUIDE §4.1 automated.
2. **IEP1 ingestion.** Unit: window boundary no-drift, manifest assembly, reconnect/timeout handling.
   Integration: capture a fixed clip → assert manifest XADD on `stream:iep1:{cam}` + frames on tmpfs.
3. **IEP2 vision.** Unit: identity manager branches, gallery, the inference-deadline fallback (spec
   iep2-vision/01). Integration: feed a real IEP1 manifest → assert `tracking_history` rows +
   `batch_complete` XADD + `inference_timeouts` field.
4. **IEP3 reconciliation.** Keep the existing good unit tests (`tests/unit/iep3/*`); add the golden
   dataset test (cross-cutting/04 R5). Integration: multi-camera `batch_complete` in →
   `global_tracking_history` out, deterministic global_ids.
5. **IEP4 alerts + IEP5 analytics.** Unit: alert evaluator edge inputs (downstream/01 R5), aggregator
   determinism/idempotency. Integration: seed `global_tracking_history` → assert alerts fired /
   `daily_store_summary` rows; re-run asserts idempotent no-op.
6. **EEP API.** Unit: schemas (replaces the missing `test_schemas.py`), the envelope/resilience/
   rate-limit specs' tests, coverage. Integration: API CRUD against a real DB → assert response_models
   + audit rows. This is TESTING_GUIDE Phase 3 automated.
7. **live_bridge + edge_agent.** Unit: WS send timeout + backpressure (downstream/01 R6), gRPC relay
   ordering. Integration: Redis live frame → WS client receives; gRPC StartCamera ordering.

## The accumulating E2E spine

One test, `tests/e2e/test_full_pipeline.py` (rewrite the existing) + the deployed-URL smoke
`tests/e2e/test_cloud.py` (cross-cutting/04 R4). The spine walks a fixed test clip through the live
compose stack and asserts at each checkpoint that exists SO FAR; as services land (the order above),
their checkpoint is appended:

```
seed store config (Phase-3 automated)
  → IEP1: frames on tmpfs + manifest on stream:iep1            [checkpoint 1]
  → IEP2: tracking_history rows + batch_complete                [checkpoint 2]
  → IEP3: global_tracking_history with deterministic global_ids [checkpoint 3]
  → IEP4/5: alerts + daily_store_summary                        [checkpoint 4]
  → EEP API: read endpoints return the aggregated results       [checkpoint 5]
  → live: WS streams a frame                                    [checkpoint 6]
```

Each checkpoint is independently skippable (marker/env) so the spine stays green while later stages
are still being built. The final spine IS the brief's "one E2E hitting the live deployed URL"
(checkpoint 5/6 against `CLOUD_URL`).

## Flexibility — contract-change protocol

Because code churn is expected:
- A failing **unit** test after a code edit → rewrite the unit test to the new internals. Routine.
- A failing **integration/E2E** test → STOP. Either the change broke a contract (fix the code) or the
  contract genuinely moved (update the seam inventory here + the contract doc + all consumers, in one
  change, and note it in the test docstring). A seam never moves silently.
- New code detail with no contract impact → no integration/E2E change; add/adjust unit tests only.
This is what keeps the suite stable through the upcoming non-architectural edits.

## Mapping the existing tree

- **Keep:** `tests/unit/iep3/*` (good, current), `tests/unit/eep/test_camera_coverage.py`,
  `tests/unit/iep2/test_gallery.py` — extend, do not delete.
- **Rewrite:** `tests/e2e/test_full_pipeline.py`, `tests/e2e/test_iep3_reconciler.py` into the spine.
- **Create:** the missing `tests/unit/test_schemas.py` (CI references it), per-service unit dirs,
  `tests/integration/`, `tests/e2e/test_cloud.py`, the golden dataset.
- **Fix:** the broken CI `eep-tests` job + add `tests/requirements.txt` (cross-cutting/04 R1/R6).
- **De-stale docs:** rewrite `docs/qa/*` stubs and prune the removed-concept sections from
  `docs/TESTING_GUIDE.md` (sections, etc.) as each phase is automated.

## Tooling & layout

Reuse cross-cutting/04 entirely: `pyproject.toml` `asyncio_mode=auto`, markers `integration`/`cloud`,
per-service conftest `sys.path` shims, `tests/requirements.txt` (pytest-asyncio, httpx, fakeredis),
function-scoped async fixtures. Unit tier needs no infra; integration tier uses the compose stack;
cloud tier is manual/pre-submission.

## Exit criteria (whole plan)

- Every service has a current `tests/unit/<S>/` suite covering its functions incl. null/edge inputs.
- Every pipeline seam has an `tests/integration/` test asserting the contract.
- The single E2E spine reaches checkpoint 5/6 and runs against `CLOUD_URL` when set.
- CI runs the full unit tree green (no missing-file references) and the integration tier on compose.
- `docs/qa/*` and TESTING_GUIDE describe only what exists.

This plan is order + seams + spine; the precise assertions live in each service's robustness spec and
are refined as code settles.
