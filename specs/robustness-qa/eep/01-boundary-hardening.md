# EEP — Read-Endpoint Degradation & Validation Hardening

Apply the cross-cutting policies to EEP's request surface: bound every list query, constrain
free-form query params, and define exactly when a read endpoint degrades gracefully versus when it
honestly fails. This is the per-service spec that consumes the error envelope, the resilience
timeouts/retries, and the rate limiter. Touches the routers under
`services/eep/app/api/routers/`. No new dependencies.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). Depends on
[cross-cutting/01-error-envelope.md](../cross-cutting/01-error-envelope.md),
[02-timeout-retry-helper.md](../cross-cutting/02-timeout-retry-helper.md),
[03-rate-limiter-request-limits.md](../cross-cutting/03-rate-limiter-request-limits.md).

---

## Motivational intent

The brief (Robustness): *"enforce input validation, constraints, request limits"* and *"a fallback
(a graceful message beats a 500)."* EEP's validation is uneven — some endpoints have good Pydantic
`Field` bounds and pagination caps (settings.py, audit.py, dev_pipeline.py, punch.py), others return
unbounded `list[...]` from a single query with no cap, and several take free-form string query params
straight into a SQL `.where()`. And the codebase has no consistent rule for what a read endpoint
should do when a dependency is down. This spec sets that rule and closes the validation gaps, so a
large store, a malformed query param, or a degraded auxiliary dependency produces a bounded,
well-formed response instead of an unbounded payload, a wasted scan, or a 500.

## Non-obvious tooling / facts (verify before you change)

- **Do NOT fabricate core data as a "fallback."** For a primary DB read (list employees, list
  shifts), an empty list when the DB is down is a lie that hides an outage. The correct behavior is
  to fail through the structured envelope (the spec-02 `command_timeout` makes it fail fast, not
  hang). Graceful degradation applies ONLY to *optional enrichment* on a read path — never to the
  core resource.
- The optional-enrichment dependencies on read paths are: **S3 presigned URLs** and **Redis
  auxiliary data**. `boto3.generate_presigned_url` is a LOCAL signing operation (no network round
  trip), so it rarely fails when MinIO is down — but a bad key/endpoint config can still raise. It is
  called per floor-plan and per camera in
  [config.py:101](../../../services/eep/app/api/routers/config.py#L101),
  [config.py:138](../../../services/eep/app/api/routers/config.py#L138), and
  [draft.py:163](../../../services/eep/app/api/routers/draft.py#L163). One bad key must not 500 the
  whole config response.
- Pagination is already correct on `audit` (`page_size le=200`), `punch-events` (`limit le=500`), and
  `dev_pipeline` (`limit le=2000`/`le=500`). Reuse that exact `Query(default=, ge=1, le=)` pattern;
  do not invent a new one.
- Several list GETs return `list[...]` from one unbounded query: shifts
  ([shifts.py:235](../../../services/eep/app/api/routers/shifts.py#L235)), shift assignments
  ([shifts.py:360](../../../services/eep/app/api/routers/shifts.py#L360)), employees
  ([employees.py:39](../../../services/eep/app/api/routers/employees.py#L39)). Shifts and assignments
  grow over time and are the real risk; employees can be large. Config-shaped lists (versions,
  cameras, zones, obstacles, members) are bounded by store config — lower risk, but still get a
  defensive hard cap.
- Free-form string query params go straight into `.where()` without an allow-list: e.g.
  `punch-events` `status: str | None` ([punch.py:79](../../../services/eep/app/api/routers/punch.py#L79))
  and `audit` `action` / `entity_type`
  ([audit.py:44](../../../services/eep/app/api/routers/audit.py#L44)). A garbage value currently
  just returns an empty set (not a crash), but it should be constrained so the contract is explicit
  and an index-friendly query is guaranteed.
- `list_members` issues an N+1 (one permission query per member,
  [members.py:49](../../../services/eep/app/api/routers/members.py#L49)) — a performance smell, NOT a
  robustness defect. Out of scope here; note it, do not fix it in this spec.

## Concise architectural map

```
read endpoint
  ├─ core DB query        ── bounded by LIMIT (R1) ; statement timeout (spec 02) ; fails → envelope
  ├─ query params         ── Enum / Query(max_length, ge/le) allow-list (R2)
  └─ optional enrichment  ── presign / Redis aux wrapped in try/except (R3)
        success → field set
        failure → field = null + logged ; core response still returned
```

## Rules (verifiable instructions)

### R1 — Hard cap on every list endpoint
Every `response_model=list[...]` GET must bound its query. For growth-prone lists (shifts, shift
assignments, employees, punch-events, audit) expose pagination: `limit: int = Query(default=50,
ge=1, le=200)` plus an `offset`/`page` where a UI needs it, and apply `.limit(limit)` (+`.offset`)
to the query with a deterministic `ORDER BY`. For config-bounded lists (versions, cameras, zones,
obstacles, members, schedules) add a defensive hard cap (`.limit(MAX_LIST_ROWS)`, default `1000`)
even without exposing pagination — so a pathological row count can never produce an unbounded
payload. No list endpoint may return the result of an uncapped `select`.

### R2 — Constrain free-form query params
Any query param used in a `.where()` filter must be validated, not free-form:
- Enumerated filters (`punch-events.status`, `audit.action`, `audit.entity_type`) become a
  `str`-backed `Enum` (or `Query(pattern=...)` allow-list). An out-of-set value yields a 422
  validation error via the envelope, not a silent empty result.
- Free-text search params (if any) get `Query(max_length=200)` and are passed as bound parameters
  (already the case via SQLAlchemy) — never string-formatted into SQL.
- Numeric params get `ge=`/`le=` bounds. Date params keep their `datetime` typing (already
  validated by Pydantic).

### R3 — Graceful degradation for optional enrichment only
Wrap each optional-enrichment call on a read path in a tight `try/except` that logs and substitutes a
null/empty value, returning the core resource regardless:
- `config.py` / `draft.py` presigned-URL generation: wrap each `generate_presigned_url_public(...)`
  call; on exception set the `*_url` field to `None` and `log.warning`. One unsignable key must not
  fail the whole version/config response.
- Any Redis auxiliary read used to ENRICH a DB response (presence, counters): wrap, default to the
  un-enriched value, log. (The spec-02 `retry_reads` may wrap the idempotent Redis read first; the
  try/except is the final fallback after retries are exhausted.)
Do NOT wrap the core DB query this way — it must surface through the envelope.

### R4 — Core reads fail honestly, fast
Core DB read failures (timeout, connection) propagate to the generic exception handler → 500
`INTERNAL_ERROR` envelope. They MUST NOT be caught and turned into an empty `200`. The spec-02
`command_timeout` guarantees the failure is bounded (no hung worker). Document this rule in the spec
and add a comment at the one or two places a well-meaning `except` might otherwise fabricate data.

### R5 — Dev/debug read endpoints return structured "unavailable"
The dev-only reads that hit Redis/DB directly with their own `aioredis.from_url`
([dev_pipeline.py](../../../services/eep/app/api/routers/dev_pipeline.py): `/gpu-status`, `/tracking`,
`/iep3`) are diagnostic, not core data. On dependency failure they return a structured
`{"available": false, "reason": <code>}`-style payload (still the envelope shape for true errors, but
a 200 "unavailable" for an expected down-dependency in dev), never a raw 500. Give their ad-hoc
`from_url` a `socket_timeout` consistent with spec 02 so they cannot hang either.

## Hard constraints & anti-patterns

- DO NOT return a fabricated empty list / zero value to mask a core DB outage. Core reads fail through
  the envelope.
- DO NOT leave any `list[...]` GET uncapped — pagination for growth-prone, defensive hard cap for the
  rest.
- DO NOT accept free-form strings into a `.where()` filter — Enum / allow-list / length-bound them.
- DO NOT widen the optional-enrichment `try/except` to swallow the core query — scope it to the single
  enrichment call.
- DO NOT string-format any value into SQL — keep SQLAlchemy bound parameters.
- DO NOT fix the `list_members` N+1 here (separate performance concern) — only add its defensive cap.
- Reuse the existing `Query(default=, ge=1, le=)` pagination idiom; do not introduce a second
  pagination style.

## Acceptance (tests — `tests/unit/eep/`)

Use the EEP `TestClient` app factory from the QA harness ([cross-cutting/04](../cross-cutting/04-qa-harness.md)),
with a fake DB/session and monkeypatched S3/Redis.

- `test_list_endpoints_capped`: each growth-prone list GET rejects `limit` above its cap (422) and
  applies `.limit()` to the query (assert via a query-capturing fake session).
- `test_config_bounded_list_hard_cap`: a config list GET issues a query with `MAX_LIST_ROWS` applied
  even when no `limit` param is given.
- `test_enum_query_param_rejected`: `GET /punch-events?status=garbage` → 422 envelope
  (`VALIDATION_ERROR`); a valid status filters correctly.
- `test_audit_action_param_constrained`: out-of-set `action`/`entity_type` → 422.
- `test_presign_failure_degrades`: monkeypatch `generate_presigned_url_public` to raise → the active
  version response returns 200 with the `display_url`/`frame_url` fields `null`, and the rest of the
  payload intact; a warning is logged.
- `test_core_db_failure_is_500_not_empty`: monkeypatch the core query to raise `TimeoutError` → the
  endpoint returns the 500 `INTERNAL_ERROR` envelope, NOT a 200 empty list.
- `test_dev_endpoint_dependency_down`: with the dev `from_url` raising/timing out → `/gpu-status`
  returns the structured "unavailable" payload, not a raw 500, and does not hang.

Acceptance is met when: no list endpoint can return an unbounded result; every filter query param is
constrained to an allow-list or bound; optional enrichment failures degrade to null fields while the
core resource still returns; core DB failures surface as the envelope (never fabricated data); and the
dev reads can neither hang nor 500 on a down dependency.

## Pinned library versions (match the running stack — add nothing)

No new dependencies. Uses `fastapi==0.115.0` (`Query`, Pydantic v2 `Field`/`Enum`),
`sqlalchemy[asyncio]==2.0.30`. The S3/Redis timeouts come from
[cross-cutting/02](../cross-cutting/02-timeout-retry-helper.md); this spec adds no clients.
