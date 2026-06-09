"""Canary traffic-splitting middleware for the EEP.

Design contract
---------------
* When CANARY_PERCENTAGE == 0 (default) this middleware is completely inert:
  every request gets model_version="production" and no canary branch executes.
* When CANARY_PERCENTAGE > 0, each request draws a uniform random float.
  If the draw < CANARY_PERCENTAGE/100 the request is tagged "canary";
  otherwise "production".
* The tag is stored on request.state.model_version — a per-request,
  thread-safe FastAPI mechanism.  Downstream code (route handlers, metrics)
  reads request.state.model_version to label Prometheus observations.
* The splitting decision is logged at DEBUG level and published to Redis key
  canary:active_percentage so external tooling can observe the live value.
* Shadow mode (app/core/shadow.py) is completely unaffected — it reads
  nothing from request.state and this module does not touch shadow.py.

Metrics
-------
EEP_REQUESTS is a Counter with labels {route, model_version}.  It is
incremented here in the middleware, once per request, after the response
is produced, so the status code is available for future extension.
The three pre-existing EEP metrics (eep_active_cameras, eep_scheduler_ticks,
eep_grpc_connections) do not get a model_version label — they measure
infrastructure state, not per-request model output.
"""
from __future__ import annotations

import logging
import random

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from prometheus_client import Counter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metric — EEP request counter split by route and model version.
# Labelled separately from the auto-instrumented HTTP metrics so the canary
# split is visible without touching prometheus_fastapi_instrumentator config.
# ---------------------------------------------------------------------------
EEP_REQUESTS = Counter(
    "eep_requests_total",
    "EEP API requests by route and model_version tag (production vs canary)",
    ["route", "model_version"],
)

# ---------------------------------------------------------------------------
# Splitter logic (pure function — easy to unit-test without the middleware)
# ---------------------------------------------------------------------------

def assign_model_version(canary_percentage: int, rand_value: float | None = None) -> str:
    """Return 'canary' or 'production' for a single request.

    Args:
        canary_percentage: integer 0–100 from settings.
        rand_value: injected in tests; drawn from random.random() in prod.

    When canary_percentage == 0 the function unconditionally returns
    'production' without calling random() — the canary path is inert.
    """
    if canary_percentage <= 0:
        return "production"
    r = rand_value if rand_value is not None else random.random()
    return "canary" if r < canary_percentage / 100.0 else "production"


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------

class CanaryMiddleware(BaseHTTPMiddleware):
    """Assigns model_version to every request and increments EEP_REQUESTS.

    Installed unconditionally in main.py; inert when CANARY_PERCENTAGE=0.
    """

    def __init__(self, app: ASGIApp, canary_percentage: int = 0) -> None:
        super().__init__(app)
        self._pct = canary_percentage
        if canary_percentage > 0:
            log.info("CanaryMiddleware active: %d%% of requests → canary", canary_percentage)
        else:
            log.info("CanaryMiddleware installed but inactive (CANARY_PERCENTAGE=0)")

    async def dispatch(self, request: Request, call_next):
        version = assign_model_version(self._pct)
        request.state.model_version = version

        log.debug(
            "canary: %s %s → model_version=%s",
            request.method, request.url.path, version,
        )

        response = await call_next(request)

        # Use the raw path template if available (avoids cardinality explosion
        # from path parameters like /store/{slug} becoming /store/my-store).
        route = request.url.path
        if hasattr(request, "scope") and request.scope.get("route"):
            route = getattr(request.scope["route"], "path", route)

        EEP_REQUESTS.labels(route=route, model_version=version).inc()
        return response
