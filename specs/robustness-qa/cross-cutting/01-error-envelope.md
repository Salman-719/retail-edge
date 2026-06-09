# Cross-cutting — EEP Error Envelope & Exception Handlers

Standardize EEP's error wire format and guarantee no unhandled exception ever returns a raw
stack trace. Adds three app-level exception handlers, normalizes the existing inconsistent
shapes onto one canonical envelope, and fixes the two routes that leak exception text. Touches
`services/eep/app/main.py` plus a tiny edit in two routers. No new dependencies.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). This is the foundation
other EEP specs build on (the rate-limiter and the read-endpoint fallbacks both emit this
envelope). Related: [02-timeout-retry-helper.md](02-timeout-retry-helper.md) (next),
[03-rate-limiter.md](03-rate-limiter.md).

---

## Motivational intent

The brief (S3 / GT1): *"return a structured error (never an unhandled stack trace)."* Today EEP
mostly does — but in three inconsistent shapes, and any code path that raises a non-`HTTPException`
(a DB hiccup, a Redis timeout, a `KeyError`) falls through to FastAPI's default 500 handler and
returns an opaque `Internal Server Error` (and, in debug servers, a traceback). Two routes go
further and deliberately put `str(exc)` into the response. During a demo, a single unhandled
exception becoming a raw 500 is exactly the "garbage when things go wrong" the brief forbids.

This spec makes the envelope uniform and total: every error — validation, raised HTTP error, or
unexpected crash — leaves EEP as the same JSON shape, with a machine `code` the frontend already
keys on, and the server logs the real cause without leaking it to the client.

## Non-obvious tooling / facts (verify before you change)

- **The wire shape is fixed by the frontend, not a free choice.** The frontend reads
  `err.response.data.detail.code` and `err.response.data.detail.error` throughout — e.g.
  [Employees.jsx:217](../../../frontend/src/pages/Employees.jsx#L217),
  [DevE2E.jsx:535](../../../frontend/src/pages/DevE2E.jsx#L535),
  [Audit.jsx:154](../../../frontend/src/pages/Audit.jsx#L154). It NEVER reads a top-level
  `data.error`. So the canonical envelope MUST be the nested form
  `{"detail": {"error": <human message>, "code": <MACHINE_CODE>}}`. Do not flatten to top-level —
  it would silently break every frontend `catch` block.
- The dominant route convention already produces this:
  `raise HTTPException(status_code=..., detail={"error": ..., "code": ...})`. FastAPI's default
  handler wraps `detail` under `"detail"`, yielding exactly the nested envelope. ~250 call sites
  follow this. **Keep it.** This spec does NOT ask you to rewrite those raises.
- The INCONSISTENT pieces to pull into line are:
  - The existing `RequestValidationError` handler in
    [main.py:158](../../../services/eep/app/main.py#L158) returns the *flat* shape
    `{"error": ..., "code": "VALIDATION_ERROR"}`. It is the odd one out; nest it.
  - Plain-string details, e.g. [debug.py:48](../../../services/eep/app/api/routers/debug.py#L48)
    `detail="action must be start or stop"` → serializes as `{"detail": "action..."}`, no `code`.
  - Two exception-text leaks: [schedules.py:160](../../../services/eep/app/api/routers/schedules.py#L160)
    `detail=f"Orchestration failed: {str(exc)}"` and the `detail=f"..."` uses in
    [debug.py:52](../../../services/eep/app/api/routers/debug.py#L52) onward.
- FastAPI raises `fastapi.HTTPException` (subclass of `starlette.HTTPException`). Routing-level
  errors (404 unknown path, 405 method) are raised as `starlette.exceptions.HTTPException` and
  bypass a handler registered only for the FastAPI subclass UNLESS you register against the
  Starlette base. Register the handler on `starlette.exceptions.HTTPException` to catch both.
- There is no central place that builds error responses today; the spec adds one tiny helper so
  the three handlers cannot drift.

## Concise architectural map

```
request
  ├─ Pydantic validation fails ─→ RequestValidationError handler ─┐
  ├─ route raises HTTPException ─→ HTTPException handler ──────────┤
  ├─ unknown path / 405         ─→ (Starlette)HTTPException handler┤→ _envelope(code, msg, status)
  └─ anything else raises       ─→ generic Exception handler ──────┘     → JSONResponse
                                       (logs traceback server-side,        {"detail":{"error","code"}}
                                        returns static message)
```

## Rules (verifiable instructions)

### R1 — One envelope builder
Add a single helper in `main.py` (or a small `app/core/errors.py`):

```python
def _envelope(status_code: int, code: str, error: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": {"error": error, "code": code}})
```

All handlers below return through this helper. The `content` is always `{"detail": {...}}` — the
nested shape the frontend reads.

### R2 — Generic `Exception` handler (the core gap)
Register `@app.exception_handler(Exception)`. It must:
- log the full traceback server-side with `logger.exception(...)` including request method + path,
- return `_envelope(500, "INTERNAL_ERROR", "Internal server error")` — a STATIC message, never
  `str(exc)`,
- never re-raise.

This is the one handler that does not exist today and is the actual GT1 violation.

### R3 — `HTTPException` handler that normalizes
Register against `starlette.exceptions.HTTPException` (catches FastAPI + routing errors). Normalize:
- if `exc.detail` is a dict that already has `"error"` and `"code"` → return
  `_envelope(exc.status_code, detail["code"], detail["error"])` (pass-through, preserves the ~250
  existing raises unchanged on the wire),
- if `exc.detail` is a plain string → wrap as
  `_envelope(exc.status_code, _code_for_status(exc.status_code), str(exc.detail))`, where
  `_code_for_status` maps common statuses to a default code (`404→"NOT_FOUND"`,
  `400→"BAD_REQUEST"`, `401→"UNAUTHORIZED"`, `403→"FORBIDDEN"`, `409→"CONFLICT"`,
  `429→"RATE_LIMITED"`, else `"HTTP_ERROR"`). This upgrades the plain-string routes (debug.py)
  to carry a `code` without touching them.
- Preserve `exc.headers` if present (e.g. `WWW-Authenticate`, and the `Retry-After` the rate
  limiter will set).

### R4 — Nest the validation handler
Change the existing `RequestValidationError` handler to return through `_envelope`:
`_envelope(422, "VALIDATION_ERROR", <message>)`. For `<message>`, keep it useful but tidy — a
compact string of the first error's `loc`+`msg` (e.g. `"body.email: value is not a valid email
address"`) rather than the raw `str(exc.errors())` dump. Field-level detail may be added as a
third key `"fields"` inside the inner object if the frontend wants it later; default to just
`error`+`code` so the shape stays uniform.

### R5 — Kill the exception-text leaks (per-route fix)
- [schedules.py:160](../../../services/eep/app/api/routers/schedules.py#L160): replace
  `detail=f"Orchestration failed: {str(exc)}"` with
  `detail={"error": "Failed to start camera orchestration", "code": "ORCHESTRATION_FAILED"}` and
  `logger.exception(...)` the real `exc` server-side.
- [debug.py:48–59](../../../services/eep/app/api/routers/debug.py#L48): convert the plain-string
  details to the `{"error","code"}` dict form (`INVALID_ACTION`, `AGENT_NOT_CONNECTED`,
  `QUEUE_FULL`). These now match the canonical shape directly instead of relying on R3's
  string-wrap.

### R6 — Handler registration order / placement
Register all handlers in `main.py` after `app = FastAPI(...)` and before/after `register_routers`
(order does not matter for exception handlers, but keep them together with the existing
`validation_error_handler`). Removing the old flat-shape body from the validation handler is part
of R4.

## Hard constraints & anti-patterns

- DO NOT flatten the envelope to top-level `{error, code}` — the frontend reads `detail.code`.
  The nested `{"detail": {...}}` shape is mandatory.
- DO NOT return `str(exc)`, `repr(exc)`, `traceback`, SQL, or any internal identifier in any error
  body. Static messages only. The real cause goes to the server log via `logger.exception`.
- DO NOT rewrite the ~250 `HTTPException(detail={"error","code"})` raises. R3 passes them through
  byte-for-byte on the wire. This spec is additive, not a mass refactor.
- DO NOT register the HTTPException handler only against `fastapi.HTTPException` — routing 404/405
  use the Starlette base and would slip through to the generic 500 handler with the wrong code.
- DO NOT swallow the generic exception silently — it MUST log the traceback. A 500 with no
  server-side log is undebuggable during the demo.
- DO NOT change status codes of existing raises. Only the body shape is normalized; `exc.status_code`
  is preserved.
- The generic handler must not itself raise (e.g. don't `json`-encode non-serializable objects);
  it only ever emits the fixed static envelope.

## Acceptance (tests — `tests/unit/eep/`)

Use FastAPI `TestClient` against a tiny app that mounts the handlers plus throwaway routes.

- `test_dict_detail_passthrough`: a route raising `HTTPException(409, {"error":"x","code":"X"})`
  → response JSON is exactly `{"detail":{"error":"x","code":"X"}}`, status 409.
- `test_string_detail_gets_code`: a route raising `HTTPException(400, "bad thing")` →
  `{"detail":{"error":"bad thing","code":"BAD_REQUEST"}}`, status 400.
- `test_unhandled_exception_is_500_envelope`: a route that does `raise RuntimeError("boom")` →
  status 500, body `{"detail":{"error":"Internal server error","code":"INTERNAL_ERROR"}}`, and
  `"boom"` appears NOWHERE in the body. Assert the traceback WAS logged (caplog).
- `test_validation_error_is_nested`: POST a body that fails Pydantic → status 422, body shape is
  `{"detail":{"error": <str>, "code":"VALIDATION_ERROR"}}` (nested, not flat).
- `test_unknown_route_404_envelope`: GET an unmapped path → status 404, body
  `{"detail":{"error": <str>, "code":"NOT_FOUND"}}`.
- `test_no_exc_text_leak_schedules` / `test_no_exc_text_leak_debug`: force the orchestration/debug
  failure path → assert the response body contains the static message + code and does NOT contain
  the underlying exception string.
- `test_headers_preserved`: a raise with `headers={"WWW-Authenticate":"Bearer"}` (or a 429 with
  `Retry-After`) → those headers survive the handler.

Acceptance is met when: no EEP code path can return a body that is not the canonical
`{"detail":{"error","code"}}` envelope; the generic handler logs every unhandled exception and
leaks none of it; the frontend's `detail.code` / `detail.error` reads keep working unchanged
(verify against the four frontend sites cited above); and the two known leak sites return static
messages.

## Pinned library versions (match the running stack — add nothing)

No new dependencies. Uses only `fastapi==0.115.0`, `starlette` (transitive), and stdlib `logging`.
Do NOT add an error-handling framework. The `_envelope` helper is ~5 lines.
