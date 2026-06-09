"""EEP rate limiting (slowapi) + request-size limits.

A global per-IP default on every route, plus tighter per-route limits on the
auth endpoints (brute-force / email-amplification protection). Redis-backed in
production so the limit is shared across the replicas=2 EEP deployment, and
fail-open: a Redis outage falls back to in-memory limiting and never 503s all
traffic. 429 (rate limited) and 413 (body too large) both emit the canonical
error envelope from app.core.errors.

Values are env-tunable. Storage defaults to REDIS_URL, or in-memory when unset
(dev / unit tests).
"""
from __future__ import annotations

import os

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.errors import envelope

# ── Limits (slowapi "<n>/<period>" expressions) ───────────────────────────────
RATE_LIMIT_GLOBAL = os.environ.get("RATE_LIMIT_GLOBAL", "120/minute")
RATE_LIMIT_AUTH = os.environ.get("RATE_LIMIT_AUTH", "10/minute")
RATE_LIMIT_PWRESET = os.environ.get("RATE_LIMIT_PWRESET", "5/minute")
RATE_LIMIT_WRITE = os.environ.get("RATE_LIMIT_WRITE", "60/minute")

# Coarse global body ceiling (~15MB). Per-upload handlers enforce the real,
# content-appropriate caps; this is just a backstop against egregious bodies.
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", "15000000"))
# Per-minute limits → a 60s Retry-After is the correct coarse hint.
_RETRY_AFTER_S = int(os.environ.get("RATE_LIMIT_RETRY_AFTER_S", "60"))

# Per-upload caps (content-appropriate; enforced in the upload handlers).
MAX_IMAGE_UPLOAD_BYTES = int(os.environ.get("MAX_IMAGE_UPLOAD_BYTES", "10000000"))  # ~10MB
MAX_XML_UPLOAD_BYTES = int(os.environ.get("MAX_XML_UPLOAD_BYTES", "2000000"))       # ~2MB


def check_upload_size(content: bytes, cap: int) -> None:
    """413 (envelope) when an uploaded file exceeds its cap. Call right after
    reading the bytes, before any decode / S3 upload."""
    if len(content) > cap:
        raise HTTPException(
            status_code=413,
            detail={"error": "Uploaded file is too large", "code": "PAYLOAD_TOO_LARGE"},
        )


def client_ip(request: Request) -> str:
    """Key by the leftmost X-Forwarded-For hop (EEP sits behind an ingress)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


def build_limiter() -> Limiter:
    storage_uri = (
        os.environ.get("RATE_LIMIT_STORAGE_URI")
        or os.environ.get("REDIS_URL")
        or "memory://"
    )
    return Limiter(
        key_func=client_ip,
        default_limits=[RATE_LIMIT_GLOBAL],
        storage_uri=storage_uri,
        # Fail-open: if the Redis store errors, fall back to in-memory limiting
        # and never let a limiter-storage outage 503 the API.
        swallow_errors=True,
        in_memory_fallback_enabled=True,
    )


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """429 through the canonical envelope, with a Retry-After hint.

    Intentionally SYNC: slowapi's SlowAPIMiddleware runs synchronously and falls
    back to its own default handler if the registered one is a coroutine. A sync
    handler is used by BOTH the middleware (global limit) and the exception-
    handler (decorated auth routes) paths, so the envelope is consistent.
    """
    return envelope(
        429,
        "RATE_LIMITED",
        "Too many requests, slow down",
        headers={"Retry-After": str(_RETRY_AFTER_S)},
    )


# Shared singleton: main.py wires it onto the app; routers import it to add
# tighter per-route limits via @limiter.limit(...).
limiter = build_limiter()


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject any request whose Content-Length exceeds the global ceiling.

    Coarse backstop only — per-upload handlers enforce the real per-type cap and
    also guard against a lying Content-Length by re-checking len(read)."""

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > MAX_REQUEST_BYTES:
                    return envelope(413, "PAYLOAD_TOO_LARGE", "Request body too large")
            except ValueError:
                pass
        return await call_next(request)
