# Consistency Audit — Top-Level Plan (spot → single-source → guardrails)

How we systematically find the cross-cutting inconsistencies that make the system hard to reason
about — the same parameter defined in many places, a coordinate that is sometimes pixels and
sometimes metres, an embedding dimension declared four ways — then collapse each to a single source of
truth and add CI guardrails so they cannot drift back. Three stages: a repeatable SCAN methodology, an
inconsistency REGISTER it produces, and the REMEDIATION + GUARDRAILS that close each entry.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). Complements the test plan
([../test-rewrite/00-PLAN.md](../test-rewrite/00-PLAN.md)) — several guardrails are CI tests.

---

## Why this is its own workstream

These are not bugs in one file; they are the same fact disagreeing with itself across files, so a
normal review never catches them. Confirmed, grounded examples:

- **Embedding dimensionality / byte-length, declared 4 ways:** `EMBEDDING_DIM = 2048` in
  [reid_service](../../../services/reid_service/service.py#L42), `embedding_dim=2048` in
  [iep3 settings](../../../services/iep3_reconciliation/app/settings.py#L40), `float32[2048]` /
  `8192 bytes` in [schema.sql](../../../services/eep/schema.sql#L776), but a STALE
  `octet_length(centroid) = 2048` with the comment "512 float32 values = 2048 bytes" in
  [0002_constraints.py](../../../services/eep/alembic/versions/0002_constraints.py#L39) (says
  superseded by 0005, comment never reconciled). Nothing forces these to agree.
- **Coordinate units, no enforced convention:** `floor_x/floor_y` (metres, from homography),
  `position_x/position_y` (camera placement — floor-plan pixels), `width_px/height_px`,
  `px_per_meter` scale, bbox `xyxy` (image pixels) appear across 30+ files
  (EEP models, IEP2 projector, IEP3 spatial_voter, IEP5 heatmap/context). px and m mix with no naming
  rule marking which is which.
- **ID identity drift (from project memory):** `camera_id` is sometimes the physical_camera UUID and
  sometimes the camera_config UUID; `local_id` is an int deterministically cast to UUID. Same name,
  different meaning by context.
- **Runtime params spread across env + Settings + compose + docs:** `WINDOW_SECONDS` (required, no
  default, injected via the compose `x-shared-config` anchor) plus per-service Settings defaults plus
  thresholds (`MIN_BBOX_CONFIDENCE`, `EMA alpha`, `SAMPLE_INTERVAL`, stream `maxlen`, timeouts) — each
  defined where it is used, with no single registry.

The goal is not to hand-fix these one by one (that re-rots), but to make each fact have exactly one
authoritative definition and a check that proves the copies match it.

## Stage 1 — The scan methodology (how to spot, by class)

Run each as a repeatable pass (ripgrep + small scripts under `scripts/consistency/`), so it can be
re-run after the upcoming code churn. Six classes:

### Class A — Forked parameters & constants
Method: build a **parameter provenance matrix**. For each known parameter, inventory every site that
DEFINES, DEFAULTS, OVERRIDES, or DOCUMENTS it:
- AST-scan every `pydantic` `Settings`/`BaseSettings` subclass across services → dump field name,
  type, default. (Services have separate Settings; some have two — e.g. IEP2's daemon vs S3-path.)
- ripgrep module-level UPPERCASE constants (`^[A-Z_]+ *=`) per service.
- Parse `docker-compose*.yml` (incl. the `x-shared-config` anchor) and `.env.example` for env keys.
- Cross-join: a parameter appearing in >1 of {Settings default, env, compose, schema, docs} with
  differing values or no single owner is an entry.

### Class B — Unit ambiguity (px / m / ms / s / bytes / dim)
Method: a **physical-quantity field audit**. Every numeric field/column/payload key that carries a
physical quantity must encode its unit in its name (`_ms`, `_px`, `_m`, `_bytes`, `_dim`) OR be listed
in a units registry. Scan:
- ripgrep coordinate/geometry names (`floor_`, `position_`, `world_`, `map_`, `_x`, `_y`, `bbox`,
  `scale`, `origin_`) and time names (`timestamp`, `window`, `_at`, `interval`, `cooldown`) across
  models, schema, payloads.
- Flag any that lacks a unit suffix and is not in the registry.
- Flag every CONVERSION site (multiply/divide by `scale`/`px_per_meter`, homography apply,
  `* 1000` / `/ 1000`) — these are unit-crossing points where a mismatch hides; each must be verified
  and annotated with the from→to units.

### Class C — Identity / naming drift
Method: an **ID concept map**. For each conceptual id (`camera`, `local`, `global`, `store`,
`version`, `employee`), enumerate every table column, model field, and payload key that names it, and
record its actual type/meaning at each site. Flag any name that means two things (the
physical-vs-config `camera_id`) or any concept with >1 name.

### Class D — Schema ↔ ORM ↔ migration drift
Method: a **declared-vs-generated diff**. Compare three sources of the persisted shape:
`services/eep/schema.sql`, the SQLAlchemy ORM metadata (`Base.metadata`), and Alembic head. Use
`alembic check` / `--autogenerate --sql` against a fresh DB and diff; a non-empty diff is drift.
Specifically flag the `metadata.create_all` "safety net" in EEP lifespan (it can reintroduce a
dropped table if a model lingers — see [[project_sections_removed]]) and stale CHECK constraints/
comments (the 0002 centroid byte-length).

### Class E — Stale docs & comments
Method: a **removed-concept / superseded-fact sweep**. ripgrep for known-dead concepts (`section`,
`section_id`) and superseded numbers (the 512 vs 2048/8192 lineage) across `docs/`, `*.md`,
docstrings, comments. The TESTING_GUIDE still has "Section Creation" (§3.3); the audit docs are dated.

### Class F — Magic numbers that should be config
Method: ripgrep numeric literals in logic (thresholds, timeouts, maxlens, dims) that duplicate a
Class-A parameter but are hardcoded inline rather than read from the single source. Each is a
candidate to fold into the canonical definition.

## Stage 2 — The inconsistency register

Each scan emits rows into `specs/robustness-qa/consistency/REGISTER.md` (the living catalogue), one
entry per inconsistency:
- `id` (e.g. CONS-001), `class` (A–F), `concept` (e.g. "embedding dim/bytes"),
- `sites` (every file:line that defines/uses it),
- `canonical truth` (the one value/meaning we declare correct),
- `severity` (does a mismatch corrupt data / just confuse?),
- `fix` (single-source action) and `guardrail` (the check that keeps it fixed),
- `status`.
The register is the deliverable of the spotting effort and the worklist for Stage 3.

## Stage 3 — Single source of truth + guardrails

For each register entry, pick the ONE authoritative source by concept type, then make copies derive
from or be verified against it:
- **Persisted shapes (dims, byte-lengths, column types, id meanings):** the **DB schema/migration** is
  canonical. Code constants and docs must match it; reconcile stale comments (0002).
- **Runtime params (window, thresholds, timeouts, maxlens):** the **env contract** is canonical
  (the compose `x-shared-config` anchor + `.env.example`); service Settings defaults must equal it or
  be removed so the env is the only knob.
- **Units:** adopt and document a **naming convention** (`_ms/_px/_m/_bytes/_dim`) + a units section in
  [docs/SERVICE_CONTRACTS.md](../../../docs/SERVICE_CONTRACTS.md); rename or annotate non-conforming
  fields; annotate every conversion site with from→to.
- **IDs:** one name per concept; where the physical-vs-config `camera_id` collision exists, rename one
  (e.g. `physical_camera_id` vs `camera_config_id`) consistently across the seam.

Guardrails (small CI tests in `tests/unit/consistency/`, run every PR — these PREVENT recurrence):
- **G1 dim/bytes parity:** assert reid `EMBEDDING_DIM`, iep3 `embedding_dim`, and the schema
  `octet_length` CHECK all agree (one derives byte-length = dim × 4).
- **G2 env/Settings parity:** assert every required env in `.env.example` has a matching Settings
  field and vice-versa; fail on orphans (catches Class A drift).
- **G3 schema/ORM no-drift:** `alembic --autogenerate` produces an EMPTY diff against ORM metadata
  (catches Class D).
- **G4 unit-suffix lint:** a test asserting physical-quantity fields (by an allow-list of stems) carry
  a unit suffix or are registered (catches Class B regressions).
- **G5 dead-concept grep:** CI greps for removed concepts (`section_id`) and fails if reintroduced
  (catches Class E).
These guardrails are also test-plan integration items; they live in CI alongside the rewritten suite.

## Sequencing & flexibility

Run Stage 1 once now to populate the register; re-run the relevant scan after each batch of the
upcoming code edits (the scans are scripts, cheap to repeat). Remediate highest-severity entries first
(data-corrupting unit/dim mismatches before cosmetic naming). Because remediation touches many files,
do each concept as ONE atomic change (definition + all consumers + guardrail) so the repo never sits
half-migrated — same discipline as the test plan's contract-change protocol.

## Exit criteria

- `REGISTER.md` catalogues every inconsistency found by the six scans, with canonical truth + fix +
  guardrail per entry.
- Each persisted-shape / runtime-param / unit / id concept has exactly one authoritative source, with
  copies deriving from or verified against it.
- Guardrails G1–G5 run green in CI and fail on reintroduced drift.
- The known offenders (embedding dim/bytes lineage, px/m coordinate naming, physical-vs-config
  camera_id, stale section references) are closed.

This plan is the methodology + register + guardrail design; the concrete per-concept fixes become
their own small specs as the register is worked.
