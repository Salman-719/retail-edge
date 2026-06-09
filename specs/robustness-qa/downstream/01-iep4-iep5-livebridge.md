# Downstream Consumers & Live Bridge — Residual Hardening

The closing per-service pass. IEP4, IEP5, and live_bridge were audited against the same axes as the
rest of the effort. The honest finding: **IEP5 needs no robustness code changes, IEP4 needs one
(SMTP timeout), live_bridge needs two (WS send timeout + exception logging).** This spec records the
audit conclusion so nobody churns already-correct code, and specs only the genuine deltas plus the
unit tests these services still owe.

Part of the robustness-qa effort. See [00-KICKOFF.md](../00-KICKOFF.md). Reuses
[cross-cutting/02-timeout-retry-helper.md](../cross-cutting/02-timeout-retry-helper.md) (SMTP timeout
value) and [cross-cutting/04-qa-harness.md](../cross-cutting/04-qa-harness.md) (test layout).

---

## Motivational intent

The brief wants every external call timed and every failure handled. For these three services most of
that is already true — and saying so plainly is part of the job. IEP5 is an idempotent one-shot Job
with a statement timeout, a single transaction, preflight guards, and clean exit codes. IEP4 is a
catch-and-continue daemon with a timed DB pool. live_bridge already has bounded per-client queues and
a reconnecting Redis reader. The residual risk is narrow: an SMTP send with no timeout, and a
WebSocket send that can block on a wedged client. Fix those, add the missing tests, and stop.

## Non-obvious tooling / facts (verify before you change)

- **IEP5 is already production-grade — do NOT add try/except, retries, or fallbacks to it.** Evidence:
  pool `command_timeout=120` + `statement_cache_size=0`
  ([iep5/db.py](../../../services/iep5_analytics/app/db.py)); the entire job is one transaction of
  idempotent `ON CONFLICT` upserts ([pipeline.py:78](../../../services/iep5_analytics/app/pipeline.py#L78));
  a `daily_summary_exists` preflight makes a re-run a no-op (at-most-once), and open-visit /
  active-person-state preflights fail fast; `main()` wraps everything in try/except →
  `logger.exception` + `sys.exit(1)` ([main.py:68](../../../services/iep5_analytics/app/main.py#L68)),
  so k8s/compose retries a clean non-zero exit, and idempotency makes the retry safe. Adding error
  handling here would only risk breaking the at-most-once guarantee.
- **IEP4 is already a resilient daemon.** The cycle loop wraps `_tick()` in try/except →
  `logger.exception("IEP4 cycle failed — continuing")`
  ([daemon.py:107](../../../services/iep4_alerts/app/daemon.py#L107)), bounded inter-tick wait via
  `asyncio.wait_for(stop_event.wait(), timeout=delay)`, pool `command_timeout=30`
  ([iep4/db.py](../../../services/iep4_alerts/app/db.py)). The email delivery caller already wraps the
  send in try/except → logs and continues ([cooldown.py:91](../../../services/iep4_alerts/app/alerts/cooldown.py#L91)).
  The ONE gap: `aiosmtplib.send(...)` at
  [delivery.py:37](../../../services/iep4_alerts/app/alerts/delivery.py#L37) has no `timeout=`, so a
  hung SMTP server stalls that tick until aiosmtplib's own default fires.
- **live_bridge already handles outbound backpressure.** Per-client `asyncio.Queue(maxsize=32)`,
  broadcast uses `put_nowait` + `except asyncio.QueueFull: pass` to drop frames for slow clients
  ([main.py:81](../../../services/live_bridge/app/main.py#L81)); the Redis reader has a reconnect loop
  with `aclose` + `sleep(2)` and clean `CancelledError` exit
  ([redis_reader.py:48](../../../services/live_bridge/app/redis_reader.py#L48)); the reader task is
  cancelled when the last client leaves. Do NOT re-spec these — they are correct.
- live_bridge gaps: the consumer loop does `await websocket.send_text(msg)` with **no timeout**
  ([main.py:112](../../../services/live_bridge/app/main.py#L112)) — a client whose TCP is wedged (not
  cleanly disconnected) blocks that coroutine indefinitely (the queue then just drops frames, but the
  coroutine and socket never release). And `except (WebSocketDisconnect, Exception): pass`
  ([main.py:113](../../../services/live_bridge/app/main.py#L113)) silently swallows EVERY error,
  including bugs — at least log the unexpected ones.

## Rules (verifiable instructions)

### R1 — IEP4 SMTP send timeout
In [delivery.py](../../../services/iep4_alerts/app/alerts/delivery.py) pass
`timeout=SMTP_TIMEOUT_S` to `aiosmtplib.send(...)`, default `10.0`, read from env
`SMTP_TIMEOUT_S` (same name/value as the EEP fix in cross-cutting spec 02 R5 — there is no shared
import, so each service restates it). The existing caller-side try/except
([cooldown.py:91](../../../services/iep4_alerts/app/alerts/cooldown.py#L91)) already turns a timeout
into a logged skip; this just bounds how long the skip takes. Add `SMTP_TIMEOUT_S` to IEP4's
`Settings` and `.env.example`.

### R2 — live_bridge WebSocket send timeout
In the `ws_live` consumer loop, replace `await websocket.send_text(msg)` with
`await asyncio.wait_for(websocket.send_text(msg), timeout=WS_SEND_TIMEOUT_S)` (default `5.0`, env
`WS_SEND_TIMEOUT_S`). On `asyncio.TimeoutError`, treat the client as dead: break out of the loop so
the `finally` block deregisters the queue and (if last) cancels the reader task. A wedged client must
release its slot, not pin a coroutine forever.

### R3 — live_bridge: log unexpected disconnects, don't swallow all
Narrow the blanket handler: catch `WebSocketDisconnect` (and `asyncio.TimeoutError` from R2) silently
as normal client-gone events, but `log.warning("ws client error camera=%s: %s", camera_id, exc)` for
any other `Exception` before falling through to `finally`. The `finally` cleanup stays exactly as is.

### R4 — IEP5: no robustness code change
Explicitly: IEP5 gets NO new try/except, retry, timeout, or fallback. The audit conclusion is that it
is already correct. The only IEP5 deliverable is the optional regression test in R6.

## Tests (verifiable acceptance)

### R5 — IEP4 unit tests (`tests/unit/iep4/`)
- `test_smtp_send_has_timeout`: monkeypatch `aiosmtplib.send`, trigger delivery, assert it is called
  with `timeout=SMTP_TIMEOUT_S`.
- `test_delivery_timeout_is_logged_not_fatal`: make the patched send raise `asyncio.TimeoutError` →
  the cooldown/delivery caller logs and the cycle continues (no exception escapes `_tick`).
- `test_alert_evaluator_edge_inputs`: feed the alert evaluator null/empty/boundary inputs (no active
  version, zero people, threshold exactly met) → no crash, correct fire/no-fire decisions. (Closes the
  Q1 "null/edge inputs" requirement for IEP4's core logic.)

### R6 — live_bridge unit tests (`tests/unit/live_bridge/`)
- `test_slow_client_dropped_on_send_timeout`: a fake WebSocket whose `send_text` never returns → after
  `WS_SEND_TIMEOUT_S` the consumer breaks, the queue is deregistered, and (last client) the reader task
  is cancelled.
- `test_queue_full_drops_frame_not_blocks`: fill a client queue past 32 → `_on_frame` drops without
  raising or blocking other clients (regression guard on existing behavior).
- `test_unexpected_error_logged`: force a non-disconnect exception in the loop → it is logged at
  warning, and cleanup still runs.

### R7 — IEP5 regression test (optional, `tests/unit/iep5/`)
A golden-style test mirroring the IEP3 golden pattern from cross-cutting spec 04: a fixed set of
`global_tracking_history`-shaped input rows and the expected `daily_store_summary` / zone summary
outputs, asserting the aggregators are deterministic and idempotent (running twice yields identical
rows, second run a no-op). Pure functions against an in-memory/throwaway schema; no model. This is the
only IEP5 work item and it is QA, not robustness.

## Hard constraints & anti-patterns

- DO NOT add error handling, retries, or fallbacks to IEP5 — it is idempotent + at-most-once and any
  added catch risks the `daily_summary_exists` guarantee. Tests only.
- DO NOT re-implement live_bridge backpressure or the Redis reconnect loop — they exist and are
  correct. Only add the send timeout and the logging.
- DO NOT remove the IEP4 cycle's catch-and-continue — the SMTP timeout is additive.
- DO NOT block the event loop in live_bridge — the send timeout is `asyncio.wait_for`, never a sync
  wait.
- Timeout values live in env-read settings (`SMTP_TIMEOUT_S`, `WS_SEND_TIMEOUT_S`), not inline
  literals.

## Pinned library versions (match the running stack — add nothing)

No new dependencies. IEP4 uses existing `aiosmtplib==3.0.1` (its `timeout=` kwarg) and `asyncpg==0.29.0`.
live_bridge uses existing `fastapi==0.111.0` / `websockets==12.0` and stdlib `asyncio`. IEP5 unchanged
(`asyncpg==0.29.0`). Test deps come from `tests/requirements.txt` (cross-cutting spec 04).
