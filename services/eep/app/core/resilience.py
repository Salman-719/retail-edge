"""Per-boundary timeouts + a narrow retry policy for EEP's external calls.

Every external boundary gets a bounded timeout so a slow/locked dependency can
never hang a request worker. Retries are applied ONLY to idempotent reads /
health checks (never writes) — a blind retry on a non-idempotent write would
risk double-application and break IEP3/IEP5's at-least-once + idempotency
guarantees. All values are env-tunable.

Imports only stdlib + tenacity/redis (botocore is imported lazily inside
s3_config), so it is safe to import early and to unit-test by file path.
"""
from __future__ import annotations

import os

import redis.exceptions as _redis_exc
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# ── Per-boundary timeouts (seconds) ───────────────────────────────────────────
DB_STATEMENT_TIMEOUT_S = float(os.environ.get("DB_STATEMENT_TIMEOUT_S", "30.0"))
S3_CONNECT_TIMEOUT_S = float(os.environ.get("S3_CONNECT_TIMEOUT_S", "3.0"))
S3_READ_TIMEOUT_S = float(os.environ.get("S3_READ_TIMEOUT_S", "10.0"))
S3_MAX_ATTEMPTS = int(os.environ.get("S3_MAX_ATTEMPTS", "3"))
REDIS_SOCKET_TIMEOUT_S = float(os.environ.get("REDIS_SOCKET_TIMEOUT_S", "2.0"))
REDIS_CONNECT_TIMEOUT_S = float(os.environ.get("REDIS_CONNECT_TIMEOUT_S", "2.0"))
SMTP_TIMEOUT_S = float(os.environ.get("SMTP_TIMEOUT_S", "10.0"))


def s3_config():
    """botocore Config: connect/read timeouts + bounded NATIVE retries.

    S3 resilience uses botocore's own retry engine — do NOT also wrap S3 calls in
    `retry_reads` (that would double-retry and fight botocore's backoff).
    """
    from botocore.config import Config

    return Config(
        connect_timeout=S3_CONNECT_TIMEOUT_S,
        read_timeout=S3_READ_TIMEOUT_S,
        retries={"max_attempts": S3_MAX_ATTEMPTS, "mode": "standard"},
    )


# ── Retry policy: idempotent reads / health checks ONLY ───────────────────────
# initial try + 2 retries, exponential backoff with jitter capped at 2s, so the
# worst case stays bounded (≈ 3 × per-call timeout + ≤2s backoff). reraise=True so
# the ORIGINAL exception (not tenacity's RetryError) reaches the error envelope.
#
# NEVER decorate a DB write, Redis stream write, S3 put/delete, SMTP send, or a
# request-scoped SQLAlchemy query (its session is poisoned after an error).
retry_reads = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.1, max=2.0),
    retry=retry_if_exception_type(
        (
            ConnectionError,
            TimeoutError,
            _redis_exc.TimeoutError,
            _redis_exc.ConnectionError,
        )
    ),
)
