"""EEP request canary tagging.

The middleware is inert when CANARY_PERCENTAGE=0. When enabled, it tags each
request as production/canary on request.state.model_version and emits a compact
Prometheus counter for canary split visibility.
"""
from __future__ import annotations

import logging
import random

from fastapi import Request
from prometheus_client import Counter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger(__name__)

EEP_REQUESTS = Counter(
    "eep_requests_total",
    "EEP API requests by route and model version tag",
    ["route", "model_version"],
)


def assign_model_version(canary_percentage: int, rand_value: float | None = None) -> str:
    if canary_percentage <= 0:
        return "production"
    value = random.random() if rand_value is None else rand_value
    return "canary" if value < canary_percentage / 100.0 else "production"


class CanaryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, canary_percentage: int = 0) -> None:
        super().__init__(app)
        self._canary_percentage = max(0, min(100, int(canary_percentage)))
        log.info("CanaryMiddleware configured at %d%%", self._canary_percentage)

    async def dispatch(self, request: Request, call_next):
        version = assign_model_version(self._canary_percentage)
        request.state.model_version = version
        response = await call_next(request)

        route = request.url.path
        if request.scope.get("route"):
            route = getattr(request.scope["route"], "path", route)
        EEP_REQUESTS.labels(route=route, model_version=version).inc()
        return response
