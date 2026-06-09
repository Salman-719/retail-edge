"""Canonical EEP error envelope + exception handlers.

Every error EEP returns has the shape::

    {"detail": {"error": <human message>, "code": <MACHINE_CODE>}}

This is the nested form the frontend reads (err.response.data.detail.code /
.error). The ~250 existing `raise HTTPException(detail={"error","code"})` sites
already produce exactly this on the wire; the handlers here normalize the
stragglers (plain-string details, routing 404/405) onto the same shape, nest the
validation handler, and — the actual GT1 fix — guarantee that NO unhandled
exception ever returns a raw stack trace.

Reused by the rate limiter and request-size middleware (they emit through
`envelope`). Imports only fastapi/starlette + stdlib, so it is safe to import in
isolation (and to unit-test by file path).
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("eep.errors")

# Default machine codes for status codes that arrive without one (plain-string
# HTTPException details, routing errors). Domain codes set explicitly at the
# raise site always take precedence.
_STATUS_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def code_for_status(status_code: int) -> str:
    return _STATUS_CODE.get(status_code, "HTTP_ERROR")


def envelope(status_code: int, code: str, error: str, headers: dict | None = None) -> JSONResponse:
    """Build the canonical error response."""
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"error": error, "code": code}},
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize every HTTPException (FastAPI + Starlette routing) onto the envelope.

    - dict detail already carrying {error, code}  -> passed through unchanged.
    - plain-string detail                          -> wrapped with a status-derived code.
    """
    detail = exc.detail
    headers = getattr(exc, "headers", None)
    if isinstance(detail, dict) and "error" in detail and "code" in detail:
        return envelope(exc.status_code, str(detail["code"]), str(detail["error"]), headers=headers)
    msg = detail if isinstance(detail, str) else str(detail)
    return envelope(exc.status_code, code_for_status(exc.status_code), msg, headers=headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 validation errors, nested onto the envelope with a tidy first-error message."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = f"{loc}: {first.get('msg', 'invalid')}" if loc else str(first.get("msg", "invalid"))
    else:
        msg = "Validation error"
    return envelope(422, "VALIDATION_ERROR", msg)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last line of defence: log the traceback server-side, return a static 500.

    Never leaks exc text, SQL, or a stack trace to the client. This is the handler
    that did not exist before — the actual 'never an unhandled stack trace' fix.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return envelope(500, "INTERNAL_ERROR", "Internal server error")


def register_error_handlers(app) -> None:
    """Register all three handlers. Order is irrelevant for exception handlers."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
