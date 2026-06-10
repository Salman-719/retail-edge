"""Guarded EEP action tool. Mints a short-lived service JWT (same scheme as EEP)
and calls EEP's REST API. Disabled unless ENABLE_EEP_ACTIONS; allowlisted actions."""
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

from app.core.config import settings

# action -> (HTTP method, path template). Only safe, reversible ops by default.
_ACTIONS = {
    "start_camera": ("POST", "/api/debug/agent/command"),
    "stop_camera": ("POST", "/api/debug/agent/command"),
}


def _service_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {"sub": settings.EEP_SERVICE_USER_ID, "account_type": "system", "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def eep_action(action: str, args: dict | None = None) -> dict:
    if not settings.ENABLE_EEP_ACTIONS:
        return {"error": "EEP actions are disabled (read-only mode)"}
    if action not in _ACTIONS:
        return {"error": f"action '{action}' not allowed", "allowed": list(_ACTIONS)}
    if not settings.EEP_SERVICE_USER_ID:
        return {"error": "EEP_SERVICE_USER_ID not configured"}
    method, path = _ACTIONS[action]
    headers = {"Authorization": f"Bearer {_service_token()}"}
    async with httpx.AsyncClient(base_url=settings.EEP_BASE_URL, timeout=15) as c:
        r = await c.request(method, path, headers=headers, json=(args or {}))
    return {"status": r.status_code, "body": r.text[:500]}
