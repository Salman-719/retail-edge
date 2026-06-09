# Cross-cutting — EEP Rate Limiter & Request Limits

Protect EEP from being spammed (brute-force auth, accidental client loops, cloud-bill blowups) and
from oversized payloads. Adds a Redis-backed `slowapi` limiter with a global default plus tighter
per-route limits on auth/write, and upload size caps on the multipart endpoints. Touches
`main.py`, the auth/write routers (decorators), and the upload handlers in `draft.py`. Adds one
dependency (`slowapi`).

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). The 429 response and the
413 response both emit the envelope from [01-error-envelope.md](01-error-envelope.md). Uses the
config-from-env pattern of [02-timeout-retry-helper.md](02-timeout-retry-helper.md).

---

## Motivational intent

The brief (Robustness / Security): *"rate limiting (slowapi or middleware) so the API can't be
spammed into a cloud-bill blowup"* and *"enforce input validation, constraints, request limits."*
EEP today has no rate limiting and no body-size enforcement. Two concrete exposures: the login /
password-reset / register endpoints can be brute-forced or used to blast password-reset emails; and
the floor-plan upload handler does `content = await file.read()` with **no size check**
([draft.py:519](../../../services/eep/app/api/routers/draft.py#L519)) — a single large POST is read
entirely into memory before any validation, an easy OOM / DoS. Rate limiting and request limits
close both.

## Non-obvious tooling / facts (verify before you change)

- **EEP runs `replicas: 2`** in production ([charts/retailvision/values.yaml](../../../charts/retailvision/values.yaml),
  `values.production.yaml`). An in-memory slowapi limiter is per-process, so two replicas would give
  ~2× the intended limit and inconsistent counting. The limiter MUST use **Redis-backed storage**
  (`storage_uri=settings.REDIS_URL`). EEP already has Redis. The staging note in
  `values.staging.yaml` (replicas pinned to 1 until Redis-backed state is deployed) confirms Redis is
  the shared coordination layer.
- **Fail-open if Redis is down.** A rate limiter whose backing store is unreachable must NOT block
  all traffic (that turns a Redis blip into a full outage during the demo). Configure
  `swallow_errors=True` on the `Limiter` so a storage error allows the request (logged), rather than
  503-ing everything. Counting accuracy is sacrificed during a Redis outage; availability wins.
- **EEP sits behind an ingress/proxy** (k8s ingress in front of the `eep` Deployment). `request.client.host`
  is then the proxy IP, not the caller. The key function must read the leftmost `X-Forwarded-For`
  entry, falling back to `request.client.host`. Do not key on the raw socket peer.
- **slowapi's default 429 body is its own shape**, not our envelope. Override the handler so a
  `RateLimitExceeded` returns the canonical `{"detail":{"error","code":"RATE_LIMITED"}}` with a
  `Retry-After` header. This composes with spec 01.
- EEP **does** receive direct multipart uploads (not just presigned-S3): floor-plan image
  ([draft.py:512](../../../services/eep/app/api/routers/draft.py#L512)), a second file upload
  ([draft.py:1533](../../../services/eep/app/api/routers/draft.py#L1533)), and calibration XML
  intrinsic/extrinsic ([draft.py:2086](../../../services/eep/app/api/routers/draft.py#L2086)). A
  blanket small body cap would break legitimate image uploads — size caps must be route-appropriate.
- `python-multipart==0.0.9` is already a dep (used by the OAuth2 form login and these uploads). No
  new dep needed for uploads.
- slowapi decorators need the `Request` object in the endpoint signature (or use the limiter's
  middleware mode). Several target endpoints may not currently take `request: Request` — adding it is
  part of the change.

## Concise architectural map

```
main.py
  ├─ Limiter(key_func=client_ip, storage_uri=REDIS_URL, swallow_errors=True,
  │          default_limits=[GLOBAL_DEFAULT])
  ├─ app.state.limiter = limiter
  ├─ SlowAPIMiddleware                      ── applies default_limits to all routes
  ├─ exception_handler(RateLimitExceeded)   ── → envelope 429 RATE_LIMITED + Retry-After
  └─ BodySizeLimitMiddleware                ── global hard ceiling on Content-Length

routers (decorators on sensitive routes)
  ├─ @limiter.limit(AUTH_LIMIT)   on login, token refresh, register, password-reset-request, invite-accept
  └─ @limiter.limit(WRITE_LIMIT)  on draft writes, member invite, employee create/update

draft.py upload handlers
  └─ enforce MAX_IMAGE_UPLOAD_BYTES / MAX_XML_UPLOAD_BYTES → 413 PAYLOAD_TOO_LARGE
```

## Rules (verifiable instructions)

### R1 — Redis-backed limiter, fail-open, XFF key
In `main.py` construct:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

def client_ip(request):
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else get_remote_address(request)

limiter = Limiter(
    key_func=client_ip,
    storage_uri=settings.REDIS_URL,
    swallow_errors=True,
    default_limits=[GLOBAL_DEFAULT],   # e.g. "120/minute"
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```
The middleware enforces `default_limits` on every route; per-route decorators tighten specific ones.

### R2 — Limits, from env (tunable defaults)
Read each as a string limit expression from env (slowapi format `"<n>/<period>"`):
- `RATE_LIMIT_GLOBAL`        default `"120/minute"`  (per IP, all routes)
- `RATE_LIMIT_AUTH`          default `"10/minute"`   (login, token refresh, register, invite-accept)
- `RATE_LIMIT_PWRESET`       default `"5/minute"`    (password-reset request — email amplification)
- `RATE_LIMIT_WRITE`         default `"60/minute"`   (state-mutating draft/member/employee writes)

Apply with `@limiter.limit(settings.RATE_LIMIT_AUTH)` etc. on the specific endpoints. The decorated
limit is in addition to (and overrides for that route) the global default. Add the four vars to
`.env.example`.

### R3 — Which routes get the tight limits
- AUTH (`RATE_LIMIT_AUTH`): `POST /auth/login`, `POST /auth/refresh`, `POST /auth/register`,
  invitation-accept, and any other credential-checking route in
  [auth.py](../../../services/eep/app/api/routers/auth.py).
- PWRESET (`RATE_LIMIT_PWRESET`): the password-reset *request* endpoint (the one that sends mail).
- WRITE (`RATE_LIMIT_WRITE`): member invite ([members.py](../../../services/eep/app/api/routers/members.py)),
  employee create/update ([employees.py](../../../services/eep/app/api/routers/employees.py)), and the
  draft mutation endpoints ([draft.py](../../../services/eep/app/api/routers/draft.py)). Read-only GETs
  rely on the global default only.
Identify each by reading the router; do not guess paths.

### R4 — 429 through the envelope
Register `@app.exception_handler(RateLimitExceeded)` returning
`_envelope(429, "RATE_LIMITED", "Too many requests, slow down")` (the helper from spec 01) WITH a
`Retry-After` header derived from the limiter (seconds until the window resets). Do not use slowapi's
default handler body.

### R5 — Global body-size ceiling (middleware)
Add `BodySizeLimitMiddleware` that, before the route runs, rejects any request whose `Content-Length`
header exceeds `MAX_REQUEST_BYTES` (default `15_000_000`, ~15MB) with a 413 envelope
(`PAYLOAD_TOO_LARGE`). This is a coarse backstop against egregious bodies; it is generous enough not
to interfere with legitimate image uploads (R6 enforces the real per-type cap). A missing/oversized
`Content-Length` on a streaming client is still caught by R6's post-read length check.

### R6 — Per-upload size caps (the real DoS fix)
In each `draft.py` upload handler, enforce a content-appropriate cap and return 413 on breach,
BEFORE expensive work (image decode / S3 upload):
- Image uploads (floor-plan, camera frame): `MAX_IMAGE_UPLOAD_BYTES` default `10_000_000` (~10MB).
- Calibration XML (intrinsic/extrinsic): `MAX_XML_UPLOAD_BYTES` default `2_000_000` (~2MB).

Enforcement is two-stage because a client can lie about `Content-Length`:
1. If `request.headers["content-length"]` is present and exceeds the cap → 413 immediately.
2. After `content = await file.read()`, assert `len(content) <= cap` → else 413. (Acceptable to read
   then check here since the coarse R5 ceiling already bounds worst case to ~15MB; do not stream-parse.)
Return the 413 as `_envelope(413, "PAYLOAD_TOO_LARGE", "Uploaded file is too large")`. Add the three
size vars to `.env.example`.

## Hard constraints & anti-patterns

- DO NOT use in-memory limiter storage — replicas=2 makes it wrong. Redis-backed only.
- DO NOT fail-closed on Redis errors — `swallow_errors=True`. A limiter outage must not become an API
  outage.
- DO NOT key on `request.client.host` directly behind the ingress — use the leftmost `X-Forwarded-For`.
- DO NOT apply a single tiny body cap globally — it breaks the 10MB image uploads. Coarse 15MB ceiling
  + per-type caps.
- DO NOT decode the image or upload to S3 before the size check — the check is the first thing in the
  handler.
- DO NOT return slowapi's or Starlette's default 413/429 JSON — both go through the spec-01 envelope.
- DO NOT rate-limit the `/health` and `/metrics` endpoints (exempt them) — Prometheus scrape and k8s
  liveness probes must never be throttled.
- Limits live in env vars; no hardcoded `"10/minute"` strings scattered in routers beyond referencing
  the settings value.

## Acceptance (tests — `tests/unit/eep/`)

Use `TestClient` with a Redis test double (fakeredis or a real Redis in the integration tier).

- `test_global_limit_enforced`: hammer any route past `RATE_LIMIT_GLOBAL` → eventually 429 with body
  `{"detail":{"error":...,"code":"RATE_LIMITED"}}` and a `Retry-After` header.
- `test_auth_limit_tighter_than_global`: `POST /auth/login` returns 429 after `RATE_LIMIT_AUTH`
  attempts, which is fewer than the global default.
- `test_pwreset_limit`: password-reset-request 429s after `RATE_LIMIT_PWRESET` attempts.
- `test_health_metrics_exempt`: many rapid `GET /health` and `/metrics` never 429.
- `test_xff_keying`: two requests with different `X-Forwarded-For` values are counted separately;
  same XFF shares a bucket.
- `test_redis_down_fails_open`: with the limiter storage raising, requests still succeed (200), and a
  warning is logged — never a 503 from the limiter.
- `test_body_ceiling_413`: a request with `Content-Length` > `MAX_REQUEST_BYTES` → 413 envelope.
- `test_image_upload_too_large_413`: floor-plan upload with a >`MAX_IMAGE_UPLOAD_BYTES` body → 413
  envelope, and S3 upload / image decode are NOT called (assert via monkeypatch).
- `test_xml_upload_too_large_413`: calibration XML over `MAX_XML_UPLOAD_BYTES` → 413.
- `test_legit_image_upload_ok`: a normal ~1MB image still uploads (no regression).

Acceptance is met when: every route is bounded by at least the global limit; auth/write routes are
tighter; 429 and 413 both emit the canonical envelope with correct headers; the limiter fails open on
Redis error; `/health` and `/metrics` are exempt; and no upload handler decodes or stores a file
before checking its size.

## Pinned library versions (match the running stack)

Add to `services/eep/requirements.txt`:
- `slowapi==0.1.9`  (pulls `limits`; compatible with `fastapi==0.115.0` / `starlette` and the pinned
  stack. Uses the existing `redis` client for storage.)

Already present, used as-is: `redis[asyncio]==5.0.4` (limiter storage), `python-multipart==0.0.9`
(uploads). Add nothing else.
