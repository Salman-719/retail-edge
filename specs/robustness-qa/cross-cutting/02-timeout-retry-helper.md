# Cross-cutting — Timeout / Retry Helper & Per-Boundary Timeouts

A single resilience policy for EEP's external boundaries: a real timeout on every external call,
and a narrow, safe retry only on idempotent reads/health. Adds `app/core/resilience.py` (tenacity
policy + helpers), wires per-boundary timeouts into the DB engine, S3 client, Redis pool, and SMTP
calls. Adds one dependency (`tenacity`) to EEP. The policy + values defined here are the contract
that the IEP specs reuse.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). Builds on
[01-error-envelope.md](01-error-envelope.md) (a timed-out/failed boundary surfaces through that
envelope). Related: [03-rate-limiter.md](03-rate-limiter.md), and the per-service specs that copy
this policy.

---

## Motivational intent

The brief (S3 / Robustness): *"timeouts so the EEP never hangs on a slow IEP; retries (once/twice,
backoff) for transient failures; fallbacks."* The EEP boundaries today are mostly un-timed: the DB
engine waits for a connection (`pool_timeout=30`) but sets **no statement timeout**, so one slow or
locked query hangs the request worker indefinitely; the S3 client has no connect/read timeout and
inherits boto3's long multi-retry defaults; the Redis pool has no `socket_timeout`; SMTP sends have
no timeout. A single slow dependency can therefore freeze a request — and in the demo, freeze the UI.

This spec gives every boundary a bounded wait, and adds a *careful* retry: only where the operation
is side-effect-free (idempotent reads, connectivity/health checks). Writes are never blind-retried —
that is the agreed rule and it protects IEP3/IEP5's at-least-once + idempotent semantics from
double-application via a different path. A failed boundary returns a fallback or the structured
error envelope; it never hangs and never silently double-writes.

## Non-obvious tooling / facts (verify before you change)

- **boto3/botocore has its OWN retry engine.** Do NOT wrap S3 calls in tenacity — that double-retries
  (tenacity × botocore = up to N×M attempts) and fights its backoff. For S3, configure resilience
  through `botocore.config.Config(connect_timeout, read_timeout, retries={...})` on the client. The
  current client ([s3_client.py](../../../services/eep/app/core/s3_client.py)) passes NO `config=` —
  that is the fix.
- **Do not retry request-scoped SQLAlchemy work.** A retry that re-runs a query on an
  already-failed `AsyncSession` is invalid (the session/transaction is poisoned after an error). The
  DB resilience here is a *timeout* (`command_timeout`) plus the existing `pool_pre_ping=True` for
  dead-connection detection — NOT a tenacity retry around handler queries. If a whole operation needs
  re-running, that is the caller's concern, not this helper's.
- `command_timeout` is an asyncpg client-side statement timeout; pass it via SQLAlchemy
  `connect_args`. It coexists with the existing `prepared_statement_cache_size: 0` (PgBouncer
  transaction mode) — keep both keys in `connect_args`.
- `aiosmtplib.send(...)` accepts a `timeout=` kwarg. EEP's
  [email.py](../../../services/eep/app/core/email.py) and IEP4's
  [delivery.py:37](../../../services/iep4_alerts/app/alerts/delivery.py#L37) both omit it today.
- Redis `ConnectionPool.from_url` accepts `socket_timeout` and `socket_connect_timeout`. The current
  pool ([redis_client.py](../../../services/eep/app/core/redis_client.py)) sets neither.
- **There is no shared importable package across services** (each has its own `requirements.txt`;
  protos are *copied*, not imported). So `resilience.py` lives in EEP and the policy/values defined
  here are COPIED by reference into the per-service specs (IEP4 SMTP timeout, live_bridge, etc.).
  IEP3 already implements equivalent inline timeouts and is exempt — do not retrofit it.
- gRPC EEP→edge already degrades (`send_command` → sent/disconnected/queue_full) and the unary dev
  calls already pass `timeout=10.0`. This spec does not touch the gRPC boundary.

## Concise architectural map

```
app/core/resilience.py
  ├─ TIMEOUTS         ── dataclass/consts read from env (defaults below)
  ├─ retry_reads      ── tenacity decorator: idempotent reads / health only
  └─ (helpers)        ── e.g. with_redis_timeout(coro), s3_config()

wired into:
  database.py     ── connect_args["command_timeout"] = DB_STATEMENT_TIMEOUT_S
  s3_client.py    ── boto3.client(..., config=resilience.s3_config())   # botocore retries, NOT tenacity
  redis_client.py ── from_url(..., socket_timeout=, socket_connect_timeout=)
  email.py        ── aiosmtplib.send(..., timeout=SMTP_TIMEOUT_S)
```

## Rules (verifiable instructions)

### R1 — Per-boundary timeouts (the dominant fix)
Add `app/core/resilience.py` exposing these values, each read from env with the default shown
(`float(os.environ.get(...))`), so deployments can tune without code change:

- `DB_STATEMENT_TIMEOUT_S`   default `30.0`  → asyncpg `command_timeout`
- `S3_CONNECT_TIMEOUT_S`     default `3.0`
- `S3_READ_TIMEOUT_S`        default `10.0`
- `S3_MAX_ATTEMPTS`          default `3`     → botocore `retries={"max_attempts":3,"mode":"standard"}`
- `REDIS_SOCKET_TIMEOUT_S`   default `2.0`   → `socket_timeout`
- `REDIS_CONNECT_TIMEOUT_S`  default `2.0`   → `socket_connect_timeout`
- `SMTP_TIMEOUT_S`           default `10.0`

Wire each into its client exactly where noted in the map. Add the seven vars to `.env.example`.

### R2 — DB statement timeout (no retry)
In [database.py](../../../services/eep/app/core/database.py), extend `connect_args`:
```python
connect_args={"prepared_statement_cache_size": 0, "command_timeout": DB_STATEMENT_TIMEOUT_S}
```
Keep `pool_pre_ping=True` and `pool_timeout=30`. Do NOT add a tenacity retry around queries.
A statement exceeding the timeout raises `asyncpg.exceptions.QueryCanceledError` /
`asyncio.TimeoutError` → propagates to the error envelope as a 500 `INTERNAL_ERROR` (or a route may
catch it and return a fallback per the read-endpoint spec).

### R3 — S3 via botocore Config (botocore retries, not tenacity)
In [s3_client.py](../../../services/eep/app/core/s3_client.py), build a shared
`botocore.config.Config` and pass it to every `boto3.client(...)`:
```python
from botocore.config import Config
def s3_config() -> Config:
    return Config(
        connect_timeout=S3_CONNECT_TIMEOUT_S,
        read_timeout=S3_READ_TIMEOUT_S,
        retries={"max_attempts": S3_MAX_ATTEMPTS, "mode": "standard"},
    )
```
Apply to both `_client()` and `_public_client()`. Do NOT wrap S3 calls in `retry_reads`.

### R4 — Redis socket timeouts
In [redis_client.py](../../../services/eep/app/core/redis_client.py), pass `socket_timeout` and
`socket_connect_timeout` to `ConnectionPool.from_url`. Keep `decode_responses=False`. Optionally add
`health_check_interval=30` so idle pooled sockets are validated. A Redis op exceeding the socket
timeout raises `redis.exceptions.TimeoutError` — read paths may catch it and fall back (see the
read-endpoint spec); write paths surface the envelope.

### R5 — SMTP timeout
Pass `timeout=SMTP_TIMEOUT_S` to `aiosmtplib.send(...)` in EEP `email.py`. (IEP4's identical fix is
restated in the IEP4 spec, same value, since there is no shared import.) The existing caller-side
`try/except` around delivery stays — a timed-out send is logged and skipped, never fatal.

### R6 — The retry policy (reads / health only)
Define one tenacity decorator in `resilience.py`:
```python
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
retry_reads = retry(
    reraise=True,
    stop=stop_after_attempt(3),                 # initial try + 2 retries
    wait=wait_exponential_jitter(initial=0.1, max=2.0),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, redis.exceptions.TimeoutError, redis.exceptions.ConnectionError)),
)
```
Apply `@retry_reads` ONLY to: idempotent connectivity/health checks (e.g. the ML-service health
wait, a Redis `PING`/read used as a readiness probe) and side-effect-free Redis GET-style reads that
sit on a request path and benefit from surviving a one-off blip. Each retried call MUST already have
its own per-attempt timeout (R1) so total worst-case latency is bounded (≈ 3 × timeout + backoff).
`reraise=True` ensures the final failure raises the real exception into the error envelope, not a
tenacity `RetryError`.

### R7 — What must NOT be retried (encode the rule)
The spec and code comments must state: no `@retry_reads` on any DB write, any Redis XADD/stream
write, any S3 PUT/DELETE/COPY, any SMTP send, or any handler that mutates state. Writes get a timeout
+ structured-error/fallback only. This preserves IEP3/IEP5 at-least-once + idempotency invariants.

## Hard constraints & anti-patterns

- DO NOT stack tenacity on top of botocore retries for S3. One retry engine per boundary.
- DO NOT retry SQLAlchemy queries on a live request session — the session is poisoned after an error.
  DB resilience is timeout + `pool_pre_ping`, nothing more.
- DO NOT retry writes (DB/Redis-stream/S3-put/SMTP). Timeout + fallback only.
- DO NOT use an unbounded or large `wait`/`stop` — total retry budget must stay small (≤ ~2s of
  backoff) so a request never hangs; the per-attempt timeout (R1) does the heavy lifting.
- DO NOT let tenacity raise `RetryError` to the client — use `reraise=True` so the real exception
  hits the envelope handler with a meaningful code.
- DO NOT hardcode the timeout values inline at call sites — they live in `resilience.py`, read from
  env, so they are tunable and consistent.
- DO NOT retrofit IEP3 (already has inline `timeout=` everywhere) — exempt.

## Acceptance (tests — `tests/unit/eep/`)

- `test_s3_client_has_config`: `_client()` is built with a botocore `Config` whose `connect_timeout`,
  `read_timeout`, and `retries["max_attempts"]` equal the configured values (introspect the client's
  `meta.config` or monkeypatch `boto3.client` and assert the `config=` kwarg).
- `test_db_engine_command_timeout`: the engine's `connect_args` includes `command_timeout` equal to
  `DB_STATEMENT_TIMEOUT_S` and still includes `prepared_statement_cache_size: 0`.
- `test_redis_pool_socket_timeout`: `from_url` is called with `socket_timeout` and
  `socket_connect_timeout` set (monkeypatch + assert kwargs).
- `test_smtp_send_has_timeout`: `aiosmtplib.send` is invoked with `timeout=SMTP_TIMEOUT_S`
  (monkeypatch `aiosmtplib.send`, trigger a send path, assert the kwarg).
- `test_retry_reads_retries_transient`: a fake coro that raises `TimeoutError` twice then returns →
  `@retry_reads` yields the value after 3 attempts; assert attempt count.
- `test_retry_reads_gives_up_and_reraises`: always raises `ConnectionError` → after 3 attempts the
  ORIGINAL exception propagates (not `RetryError`).
- `test_retry_reads_does_not_swallow_nontransient`: raises `ValueError` → not retried, raised on the
  first attempt.
- `test_total_retry_budget_bounded`: with patched fast timers, assert worst-case attempts ≤ 3 and the
  backoff is bounded by `max=2.0`.

Acceptance is met when: every EEP external boundary has a bounded per-call timeout sourced from
`resilience.py`; S3 uses botocore retries only; no write path is wrapped in `retry_reads`; the retry
decorator reraises the real exception; and a deliberately slow/locked dependency causes a bounded
failure (envelope or fallback) instead of a hung worker.

## Pinned library versions (match the running stack)

Add to `services/eep/requirements.txt`:
- `tenacity==8.3.0`  (pure-Python, no native deps; compatible with Python 3.11 and the pinned
  `fastapi==0.115.0` / `pydantic` v2 stack. 8.2.x–8.5.x also work; pin 8.3.0 for reproducibility.)

Already present, used as-is: `boto3==1.34.69` (botocore `Config`), `redis[asyncio]==5.0.4`,
`sqlalchemy[asyncio]==2.0.30` + `asyncpg==0.29.0`, `aiosmtplib==3.0.1`. Add nothing else.
