"""EEP rate-limiter + request-size tests.

Uses in-memory limiter storage (prod uses Redis); the limiting LOGIC is the same.
Imports app.core.ratelimit via the eep conftest's services/eep path shim.
"""
from fastapi import FastAPI, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.testclient import TestClient

from app.core import ratelimit as rl
from app.core.errors import register_error_handlers
from app.core.ratelimit import BodySizeLimitMiddleware, check_upload_size, rate_limit_handler


def _app(limit: str = "3/minute") -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)  # HTTPException(413) from check_upload_size -> envelope
    limiter = Limiter(key_func=get_remote_address, default_limits=[limit], storage_uri="memory://")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)

    @app.get("/ping")
    async def ping(request: Request):
        return {"ok": True}

    @app.post("/upload")
    async def upload(request: Request):
        body = await request.body()
        check_upload_size(body, 100)  # 100-byte cap for the test
        return {"size": len(body)}

    return app


def test_global_limit_returns_429_envelope():
    client = TestClient(_app("3/minute"))
    codes = [client.get("/ping").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    r = client.get("/ping")
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "RATE_LIMITED"
    assert r.headers.get("retry-after") is not None


def test_under_limit_passes():
    client = TestClient(_app("100/minute"))
    assert client.get("/ping").status_code == 200


def test_upload_too_large_413_envelope():
    client = TestClient(_app("100/minute"))
    assert client.post("/upload", content=b"x" * 50).status_code == 200
    r = client.post("/upload", content=b"x" * 200)
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "PAYLOAD_TOO_LARGE"


def test_body_ceiling_413(monkeypatch):
    monkeypatch.setattr(rl, "MAX_REQUEST_BYTES", 10)
    client = TestClient(_app("100/minute"))
    r = client.post("/upload", content=b"x" * 50)  # 50 > 10-byte ceiling
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "PAYLOAD_TOO_LARGE"


def test_check_upload_size_helper():
    import pytest
    from fastapi import HTTPException

    check_upload_size(b"x" * 10, 100)  # under cap: no raise
    with pytest.raises(HTTPException) as ei:
        check_upload_size(b"x" * 200, 100)
    assert ei.value.status_code == 413
