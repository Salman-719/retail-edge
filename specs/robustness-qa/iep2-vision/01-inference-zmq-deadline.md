# IEP2 — Inference ZMQ Deadline, Fallback & Pending-Future Leak Fix

Spec for the IEP2→inference boundary (yolo-service and reid-service over ZMQ). This is the
single worst robustness defect in the system: a detection/embedding call that never returns
hangs a camera worker forever. This spec adds a per-request deadline, a safe fallback, and
fixes the unbounded `_pending` future leak. It changes only the two ZMQ clients plus a small
hook in the batch-close path for observability. No call-site logic changes.

Part of the robustness-qa effort. See the audit matrix in [00-KICKOFF.md](../00-KICKOFF.md).
Related (future): IEP2 Redis/DB boundary spec; the cross-cutting timeout/retry helper (EEP-side).

---

## Motivational intent

The brief: *"the system must not crash or return garbage when things go wrong"* and *"if the
system fails during the demo, grading stops."* For IEP2 the failure is not a crash — it is a
silent hang. yolo-service or reid-service can stall, drop a message, or fall behind under
multi-camera load. When that happens today, `YoloClient.detect()` and `ReidClient.extract()`
do `return await fut` on a Future that is never resolved. The camera worker blocks on that
`await` indefinitely: no frames advance, no `batch_complete` is published, IEP3 never gets the
window, the demo freezes. Worse, every blocked request leaves a permanent entry in the client's
`_pending` dict — an unbounded memory leak that also accumulates across timed-out requests.

The fix is small because the fallback already exists in the pipeline. A frame with no detections
(`[]`) is a normal frame — ByteTrack coasts the tracks. A crop with no embedding (`None`) is
already handled at every ReID gather site (`if emb is not None:`). So a deadline that returns the
empty value is loss-tolerant and never produces garbage. We make a stalled inference call
degrade to "that frame contributed nothing," not "the whole camera is dead."

## Non-obvious tooling / facts (verify before you change)

- Both clients use the same architecture: a PUSH socket to the shared input, a per-camera bound
  PULL socket, a background `_reader_loop` that resolves Futures by `request_id`, and a
  `_pending: dict[str, asyncio.Future]`. The fix is identical in shape for both.
  See [detector.py](../../../services/iep2_vision/detector/detector.py) and
  [reid.py](../../../services/iep2_vision/reid/reid.py).
- The `_reader_loop` already swallows every non-cancel exception with a `log.warning` and keeps
  looping. That is fine and stays. It is NOT a deadline — it never resolves or fails a pending
  Future, so a missing/late reply is invisible to the awaiting caller. The deadline must live at
  the `await fut` site, not in the reader loop.
- There are TWO consumer paths and both instantiate these same client classes: the S3/tmpfs path
  (`_load_and_detect_s3` → `detect_batch`, around [runtime.py:413](../../../services/iep2_vision/runtime.py#L413))
  and the daemon path (around [runtime.py:825](../../../services/iep2_vision/runtime.py#L825)).
  Because the deadline lives inside the client, BOTH paths are fixed by one change. Do not patch
  the call sites.
- The clients already read deployment config straight from `os.environ` (e.g. `YOLO_INPUT_SOCK`,
  `REID_INPUT_SOCK`). Follow that exact pattern for the new timeout env vars — do NOT try to
  thread them through the two different `Settings` shapes (the daemon's nested
  `class Settings(BaseSettings)` at [runtime.py:542](../../../services/iep2_vision/runtime.py#L542)
  and the S3-path settings). Reading from env in the client keeps both paths consistent.
- IEP2 is NOT a Prometheus scrape target. There is no `iep2` job in
  [monitoring/prometheus.yml](../../../monitoring/prometheus.yml) and the per-camera `iep2_vision`
  pods are spawned dynamically by the Edge Agent / k3s — they have no stable scrape address. IEP2
  has no `prometheus-client` dependency. Therefore the timeout counter is surfaced via structured
  logs and the existing `batch_complete` Redis payload, NOT a `/metrics` endpoint. A scraped
  endpoint for ephemeral IEP2 pods (pushgateway or k8s SD) is explicitly out of scope here and
  becomes its own infra spec if wanted.
- `batch_complete` is published in two places with slightly different code:
  `_publish_batch_complete` ([runtime.py:263](../../../services/iep2_vision/runtime.py#L263)) and
  an inline `server_redis.xadd` in the daemon path
  ([runtime.py:911](../../../services/iep2_vision/runtime.py#L911)). Both must gain the new field.

## Concise architectural map

```
camera worker loop
  └─ detect_batch(frames, ts)            ── YoloClient (detector.py)
        send N frames on PUSH            ── shared yolo_input.sock (all cameras)
        await each Future WITH DEADLINE  ── NEW: asyncio.wait_for, batch-wide budget
        on deadline → [] for that frame  ── NEW: pop _pending, count, log
  └─ manager.process_frame(...)
        gather(extract(...) for crops)   ── ReidClient (reid.py)
        await each Future WITH DEADLINE  ── NEW: asyncio.wait_for(REID_REQUEST_TIMEOUT_S)
        on deadline → None               ── NEW: pop _pending, count, log
  └─ batch close
        batch_complete XADD              ── NEW field: inference_timeouts=<delta>
        "Batch stats" log line           ── NEW: inference_timeouts=<delta>
```

## Rules (verifiable instructions)

### R1 — Per-request deadline on the single-call paths
In `YoloClient.detect()` and `ReidClient.extract()`, replace the bare `return await fut` with a
deadline:

```python
try:
    return await asyncio.wait_for(fut, timeout=self._timeout_s)
except asyncio.TimeoutError:
    self._timeouts += 1
    log.warning("inference timeout camera=%s req=%s after %.1fs",
                self._camera_id, req_id, self._timeout_s)
    return []        # YoloClient.detect  → empty detections
    # return None    # ReidClient.extract → no embedding (handled by callers)
finally:
    self._pending.pop(req_id, None)
```

The `finally` pop is mandatory and is the leak fix: it runs on success, timeout, and cancel, so
`_pending` can never grow without bound. `detect()` returns `[]`; `extract()` returns `None`.

### R2 — Batch-wide deadline on `detect_batch`
`detect_batch` sends all frames, then awaits. Give the whole batch ONE wall-clock budget that
scales with batch size, because the shared yolo input socket serves every camera sequentially and
a large batch queued behind other cameras must not false-timeout on its tail frames:

```
batch_budget = YOLO_REQUEST_TIMEOUT_S + YOLO_BATCH_PER_FRAME_S * len(frames)
```

with `YOLO_BATCH_PER_FRAME_S` default `0.1`. Compute one `deadline = loop.time() + batch_budget`
at the moment the last frame is sent. Await each real Future with
`asyncio.wait_for(fut, timeout=max(0.0, deadline - loop.time()))`. A frame whose Future is not
resolved by the shared deadline yields `[]` for that frame only; the rest of the batch is
unaffected. Use `asyncio.gather(..., return_exceptions=True)` OR await each future in a loop with
its own try/except — either way, one slow frame must never sink the others, and every dispatched
`req_id` must be popped from `_pending` in a `finally`. Frames that failed JPEG encode keep their
existing pre-resolved `[]` Future and never count as timeouts.

### R3 — Config from env, documented defaults
Both clients read their deadlines once in `__init__` from `os.environ`, mirroring the existing
socket-address pattern:

- `YOLO_REQUEST_TIMEOUT_S` default `5.0`  (used by `detect` and as the base term of the batch budget)
- `YOLO_BATCH_PER_FRAME_S` default `0.1`  (per-frame term of the batch budget)
- `REID_REQUEST_TIMEOUT_S` default `3.0`  (used by `extract`)

Parse with `float(os.environ.get(NAME, DEFAULT))`. Add these three vars to the daemon
`Settings` field list and to `.env.example` for documentation/injection parity, even though the
clients read them from the environment directly (the Edge Agent ConfigMap must forward them to
the IEP2 pod env — see the ConfigMap note in [project overview]; confirm against the real
ConfigMap builder before claiming done).

### R4 — Timeout counter, exposed via logs + `batch_complete`
Each client holds `self._timeouts: int`, incremented on every deadline hit (R1, R2). The runtime
snapshots `yolo_client._timeouts + reid_client._timeouts` at batch start and again at batch close;
the per-batch delta is:

- added as a field `"inference_timeouts": str(delta)` to BOTH `batch_complete` payloads
  (`_publish_batch_complete` fields dict and the inline daemon `xadd` fields dict), and
- appended to the existing "Batch stats" `log.info` line as `inference_timeouts=%d`.

A non-zero value at the central consumer (IEP3 / a human tailing logs) is the signal that an
inference service is degraded, without IEP2 needing a scrape endpoint. Do not add a second health
signal: the IEP2 health gRPC keeps reporting SERVING/NOT_SERVING purely off the existing
yolo/osnet TCP health checks.

### R5 — Reader loop unchanged in contract
Leave `_reader_loop` resolving Futures by `request_id` and swallowing its own exceptions. After
R1/R2 a late reply that arrives for an already-popped `req_id` simply finds no pending Future
(`self._pending.pop(req_id, None)` returns `None`) and is dropped — which is correct. Confirm the
loop does `self._pending.pop(req_id, None)` (it already does) so a late reply is a no-op, not a
KeyError.

## Hard constraints & anti-patterns

- DO NOT add a retry around an inference call. A timed-out frame is dropped, not retried — the
  next frame is already arriving, the window is fixed-length, and at the configured `target_fps`
  a stale re-detection is worthless. This matches the agreed policy: reads/health may retry,
  inference frames do not.
- DO NOT change `process_frame` or any ReID gather site. They already treat `None` as "no
  embedding." Re-deriving fallback there would duplicate logic and risk double-counting.
- DO NOT block the event loop. The deadline must be `asyncio.wait_for` on the existing Future;
  never `socket.poll()` with a sync wait, never `time.sleep`.
- DO NOT let `detect_batch` raise out of one frame's timeout and abandon the rest. One frame's
  failure is `[]`, the batch returns a full-length list aligned to inputs.
- DO NOT introduce a `/metrics` endpoint or `prometheus-client` dependency in this spec. Counter
  goes to logs + `batch_complete` only (decided: ephemeral pods have no scrape path).
- DO NOT widen the deadline to cover a fully-dead service "just in case." Dead-service detection
  is the health check's job; the deadline only protects against per-request stalls.
- Preserve the strict batch-close order (centroids → `batch_complete` → XACK → cleanup). The new
  field is added to the existing `batch_complete` XADD; it must not move XACK earlier or later.

## Acceptance (unit tests — `tests/unit/iep2/`)

All tests use a fake yolo/reid service: a coroutine the client's reader loop reads from, which can
be told to reply, to never reply, or to reply late. No real ZMQ, no GPU. Drive with
`pytest.mark.asyncio` and a fast monkeypatched timeout (e.g. set the env vars to 0.05s) so tests
run in milliseconds.

- `test_detect_returns_empty_on_timeout`: service never replies → `detect()` returns `[]` within
  ~`YOLO_REQUEST_TIMEOUT_S`, and `client._timeouts == 1`.
- `test_detect_no_pending_leak_on_timeout`: after the above, `client._pending == {}`.
- `test_detect_success_unaffected`: service replies normally → real detections returned,
  `client._timeouts == 0`, `_pending` empty.
- `test_detect_batch_partial_timeout`: 3 frames, middle one never replies → result is length-3,
  index 1 is `[]`, indices 0 and 2 carry real detections, `client._timeouts == 1`, `_pending`
  empty.
- `test_detect_batch_budget_scales`: with `YOLO_BATCH_PER_FRAME_S` set, a batch of N frames whose
  replies arrive just under `base + per_frame*N` all succeed (no false timeouts); one arriving
  just after the budget yields `[]`.
- `test_extract_returns_none_on_timeout`: reid never replies → `extract()` returns `None`,
  `_timeouts == 1`, `_pending` empty; assert `process_frame` with a `None`-returning mock client
  still completes and assigns/keeps a `local_id` (fallback is loss-tolerant).
- `test_late_reply_after_timeout_is_noop`: service replies AFTER the deadline → the reader loop
  finds no pending Future and does not raise; client stays consistent.
- `test_batch_complete_carries_timeout_count`: drive one batch with K induced timeouts and assert
  the published `batch_complete` fields include `inference_timeouts == str(K)` and the batch-stats
  log line contains the same count. (Integration-lite: may live in `tests/e2e/` if it needs the
  runtime loop; a pure-unit version can assert the runtime's snapshot-delta helper directly.)

Acceptance is met when: every test above passes; `_pending` is provably empty after any timeout;
no inference call can block longer than its configured deadline; and a wedged yolo/reid service
produces a steady stream of empty-but-advancing batches with a non-zero `inference_timeouts`
count, never a frozen camera.

## Pinned library versions (match the running stack — add nothing)

No new dependencies. This spec uses only the standard library (`asyncio`, `os`) plus what IEP2
already pins: `pyzmq==25.1.2`, `msgpack==1.0.8`, `numpy==1.26.4`. Do NOT add `prometheus-client`,
`tenacity`, or any retry/metrics library to `services/iep2_vision/requirements.txt` for this work.
