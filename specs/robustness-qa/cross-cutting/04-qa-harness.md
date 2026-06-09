# Cross-cutting — QA Harness, Golden Dataset & Live E2E

The shared test scaffolding every other spec's acceptance section slots into: a real pytest layout,
per-service `conftest` import shims, a single test-requirements file, corrected CI, the golden-dataset
format for the model-regression test, and the one live-URL E2E. Fixes the currently-broken CI job and
the missing async test dependency. Touches `tests/`, `pyproject.toml`, `.github/workflows/ci.yml`,
and `testing-data/golden/`. No service code changes.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). The acceptance tests in
[iep2-vision/01](../iep2-vision/01-inference-zmq-deadline.md) and the three cross-cutting EEP specs
([01](01-error-envelope.md), [02](02-timeout-retry-helper.md),
[03](03-rate-limiter-request-limits.md)) all assume the layout defined here.

---

## Motivational intent

The brief (Q1/Q2): *"automated, not manual"* tests — unit (each function in isolation, incl. null/edge
inputs), integration (IEP1+IEP2+EEP together), **one** E2E hitting the live deployed URL, and
regression/golden-dataset tests run after every model update. The foundation exists but is thin and
partly broken: real unit coverage is IEP3-only, the QA strategy docs are stubs full of `TODO`
referencing files that do not exist (`test_cloud.py`, `test_golden_dataset.py`), the CI `eep-tests`
job runs a `tests/unit/test_schemas.py` that is **not in the tree** (so the job fails), and the unit
CI installs bare `pytest` with **no `pytest-asyncio`** even though `pyproject.toml` sets
`asyncio_mode=auto`. This spec makes the harness real and runnable so every other spec's tests can
actually execute in CI.

## Non-obvious tooling / facts (verify before you change)

- `pyproject.toml` already sets `[tool.pytest.ini_options] asyncio_mode="auto"`,
  `testpaths=["tests"]`. Keep these. `auto` mode means async tests need NO `@pytest.mark.asyncio` but
  DO need `pytest-asyncio` installed.
- **There is no shared installable package.** Tests import a service via a `sys.path.insert` shim in a
  `conftest.py`, exactly as [tests/unit/iep3/conftest.py](../../../tests/unit/iep3/conftest.py) does
  (`sys.path.insert(0, ".../services/iep3_reconciliation")` then `from app... import`). Every
  service's unit dir needs its own such conftest; do NOT try to `pip install -e` the services.
- **CI is currently broken / misaligned** ([.github/workflows/ci.yml](../../../.github/workflows/ci.yml)):
  the `eep-tests` job runs `tests/unit/test_schemas.py::TestStoreCreate` and four sibling classes that
  do not exist in the repo, and installs only `pytest` (no `pytest-asyncio`). Both must be fixed here.
- `pytest-asyncio==0.23.6` is pinned only in [tests/e2e/requirements.txt](../../../tests/e2e/requirements.txt).
  Function-scoped fixtures are required under 0.23.6 (one event loop per test function — the e2e file
  documents the "Future attached to a different loop" gotcha). Keep fixtures function-scoped.
- The golden dataset belongs in `testing-data/golden/` per
  [docs/qa/REGRESSION_STRATEGY.md](../../../docs/qa/REGRESSION_STRATEGY.md): 3 simulated cameras, 2
  persons, PRE-COMPUTED OSNet embeddings (no model invocation, no randomness), expected global_id
  assignment. IEP3 is deterministic on fixed embeddings, so the test asserts exact output. The
  embeddings are committed as fixed bytes/`.npy` so the test runs with NO GPU and NO model.
- The live E2E has no deployed URL yet (it is a `TODO` in the strategy doc). Gate it on a `CLOUD_URL`
  env var and a `--cloud` opt-in flag; skip cleanly when unset so CI and local runs are green without
  it. Do not hardcode a URL.
- `flake8` in CI ignores `F401` etc. and `--max-line-length=120`; `black --line-length=120` runs
  check-only with `continue-on-error`. New test files must pass flake8 with those ignores.

## Concise architectural map

```
tests/
  conftest.py                     ── repo-root shared fixtures (env defaults, markers)
  requirements.txt                ── NEW: single unit+integration test dep set (pytest, pytest-asyncio, httpx, fakeredis, ...)
  unit/
    eep/    conftest.py           ── sys.path shim → services/eep ; TestClient app factory
            test_*.py             ── envelope, resilience, rate-limit, schemas, coverage
    iep2/   conftest.py           ── sys.path shim → services/iep2_vision ; fake yolo/reid
            test_*.py             ── inference deadline, gallery
    iep3/   conftest.py (exists)  ── unchanged
            test_golden_dataset.py── NEW: regression vs testing-data/golden/
  integration/                    ── NEW tier: IEP1+IEP2+EEP via compose (marker: integration)
  e2e/
    test_full_pipeline.py (exists)
    test_cloud.py                 ── NEW: single live-URL E2E, gated on CLOUD_URL + --cloud

testing-data/golden/             ── fixed embeddings (.npy) + expected_assignments.json
pyproject.toml                   ── markers: integration, cloud ; asyncio_mode=auto (kept)
.github/workflows/ci.yml         ── FIXED unit job + real test tree
```

## Rules (verifiable instructions)

### R1 — Single test-requirements file
Add `tests/requirements.txt` pinning the unit/integration test deps, compatible with the running
stack: `pytest==8.1.1`, `pytest-asyncio==0.23.6`, `httpx==0.27.0` (FastAPI `TestClient`),
`fakeredis==2.23.x` (rate-limiter + Redis tests without a server), plus `asyncpg==0.29.0`,
`redis[asyncio]==5.0.4` for integration. The existing `tests/e2e/requirements.txt` stays for the
compose/e2e image; this new file is for the unit+integration tiers. Do NOT add test deps to any
service `requirements.txt`.

### R2 — Per-service conftest import shims
Add `tests/unit/eep/conftest.py` and `tests/unit/iep2/conftest.py` mirroring the IEP3 pattern:
`sys.path.insert` the service dir, then expose reusable fixtures. The EEP conftest provides an `app`
TestClient factory that mounts the real exception handlers (so envelope tests are exercised against
production wiring) and a `fake_redis` fixture. The IEP2 conftest provides a fake yolo/reid endpoint
(a coroutine the client reader loop reads from, controllable to reply / never-reply / reply-late) —
this is the harness the IEP2 deadline tests in spec 01 require.

### R3 — Pytest markers for the tiers
In `pyproject.toml` register markers:
```toml
markers = [
  "integration: requires the docker-compose stack (postgres/redis/minio)",
  "cloud: hits the live deployed URL; requires CLOUD_URL and --cloud",
]
```
Unit tests (default) need no infra and run everywhere. Integration tests are `@pytest.mark.integration`.
The live E2E is `@pytest.mark.cloud`.

### R4 — Live E2E gated and skip-clean
Add `tests/e2e/test_cloud.py`: read `CLOUD_URL` from env; register a `--cloud` flag via a root
`conftest.py` `pytest_addoption`; if `--cloud` is absent OR `CLOUD_URL` is unset, `pytest.skip` the
module. The test fires a real HTTP request (`httpx`) at `GET {CLOUD_URL}/health` and one read endpoint,
asserting 200 and the expected JSON shape (and, where seeded, that a `global_id` exists). This is the
single deployment-smoke E2E the brief asks for. Document the run command in the strategy doc:
`CLOUD_URL=https://... pytest tests/e2e/test_cloud.py --cloud -v`.

### R5 — Golden dataset format + test
Create `testing-data/golden/`:
- `embeddings.npy` (or a small set of per-camera `.npy`): fixed float32 OSNet vectors for the 2
  persons across 3 cameras, committed bytes — no model run.
- `expected_assignments.json`: the canonical mapping (person A → global X, person B → global Y) and
  the input position rows.
Add `tests/unit/iep3/test_golden_dataset.py`: load the fixtures, run IEP3's matching/resolution on
them (pure functions, no DB/Redis), assert the global_id assignment is EXACTLY the expected mapping
(no false merges, no missed links). Tolerance is zero — deterministic. This is the
"run-after-every-model-update" regression gate referenced by
[REGRESSION_STRATEGY.md](../../../docs/qa/REGRESSION_STRATEGY.md).

### R6 — Fix and expand the CI test job
In `.github/workflows/ci.yml` `eep-tests`:
- install `-r tests/requirements.txt` (gets `pytest-asyncio`) in addition to
  `services/eep/requirements.txt`,
- replace the non-existent `tests/unit/test_schemas.py::...` invocation with `pytest tests/unit -v`
  (runs the whole unit tree: eep + iep2 + iep3 + golden dataset). Unit tier needs no services beyond
  the import shims.
Add (or fold into the existing `docker-smoke`) an `integration` job that brings up the compose stack
and runs `pytest -m integration`. The `cloud` marker is NOT run in CI (manual pre-submission only).
Rename the job(s) honestly (it now runs more than EEP).

### R7 — Update the strategy docs to match reality
Replace the `TODO`/stub rows in [docs/qa/TEST_STRATEGY.md](../../../docs/qa/TEST_STRATEGY.md) and
[docs/qa/REGRESSION_STRATEGY.md](../../../docs/qa/REGRESSION_STRATEGY.md) with the real file paths and
run commands defined here, so the docs stop referencing non-existent files. Fill the coverage-target
section with the actual `pytest --cov` command. (Docs only — no behavior.)

## Hard constraints & anti-patterns

- DO NOT `pip install -e` services or add a shared package — use the `conftest` `sys.path` shim, the
  established pattern.
- DO NOT add `pytest`/`pytest-asyncio`/test-only libs to any service `requirements.txt` — they belong
  in `tests/requirements.txt`.
- DO NOT leave CI pointing at `tests/unit/test_schemas.py` — that file does not exist; the job must run
  the real tree.
- DO NOT invoke a model or GPU in the golden-dataset test — embeddings are committed fixtures. Zero
  randomness, exact assertion.
- DO NOT hardcode a deployed URL — `CLOUD_URL` env + `--cloud` opt-in; skip cleanly when absent so the
  default suite is green offline.
- DO NOT use session/module-scoped async fixtures under pytest-asyncio 0.23.6 — keep them
  function-scoped to avoid cross-loop errors.
- DO NOT make unit tests depend on a running Postgres/Redis/MinIO — those are the `integration` tier.
  Unit tests use fakes (`fakeredis`, monkeypatch, the fake yolo/reid endpoint).
- The single live E2E stays SINGLE — it is a deployment smoke test, not a second integration suite.

## Acceptance (self-verifying — the harness proves itself)

- `pytest tests/unit -v` runs green with no infra, executing eep + iep2 + iep3 + golden-dataset tests
  (and is what CI runs).
- `test_golden_dataset` passes deterministically with the committed fixtures and FAILS if any expected
  global_id assignment changes (flip one expected value to confirm it catches regressions).
- `pytest -m cloud` with `CLOUD_URL` unset / no `--cloud` → all cloud tests SKIPPED (not failed); with
  a reachable `CLOUD_URL` and `--cloud` → the smoke assertions run.
- `pytest -m integration` is skipped by default and runs against the compose stack when selected.
- CI `eep-tests` (renamed) installs `tests/requirements.txt`, runs `pytest tests/unit`, and no longer
  references a missing file; the run is green.
- The EEP and IEP2 conftest fixtures exist and are consumed by the spec-01/02/03 and IEP2 acceptance
  tests (those suites import the fakes defined here).

Acceptance is met when: the full unit tree runs green in CI with async support; the golden-dataset
regression gate exists and is deterministic; the live E2E is wired but skip-clean without a URL; the
integration tier is selectable; and the strategy docs reference only files that exist.

## Pinned library versions (match the running stack)

`tests/requirements.txt`: `pytest==8.1.1`, `pytest-asyncio==0.23.6`, `httpx==0.27.0`,
`fakeredis==2.23.5`, `asyncpg==0.29.0`, `redis[asyncio]==5.0.4`. (All compatible with Python 3.11 and
the pinned service stack.) Service `requirements.txt` files are untouched. `numpy==1.26.4` (already
present) loads the golden `.npy` fixtures.
