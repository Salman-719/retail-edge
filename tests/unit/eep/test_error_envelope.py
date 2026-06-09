"""EEP error-envelope handler tests.

Verifies the canonical {"detail": {"error", "code"}} shape for every error path:
dict-detail pass-through, string-detail code derivation, nested validation
errors, routing 404, header preservation, and — the core fix — an unhandled
exception becoming a static 500 that leaks no traceback.

errors.py imports only fastapi/starlette (no `app.*`), so we load it by file
path to avoid the cross-service `app` package-name collision.
"""
import importlib.util
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.testclient import TestClient

_ERRORS = (
    Path(__file__).resolve().parents[3] / "services" / "eep" / "app" / "core" / "errors.py"
)


def _load_errors():
    spec = importlib.util.spec_from_file_location("eep_errors_under_test", _ERRORS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


errors = _load_errors()


class _Body(BaseModel):
    n: int


def _client() -> TestClient:
    app = FastAPI()
    errors.register_error_handlers(app)

    @app.get("/dict-detail")
    async def _dict_detail():
        raise HTTPException(status_code=409, detail={"error": "already exists", "code": "TAKEN"})

    @app.get("/string-detail")
    async def _string_detail():
        raise HTTPException(status_code=400, detail="bad thing")

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("boom-secret-do-not-leak")

    @app.get("/with-headers")
    async def _with_headers():
        raise HTTPException(
            status_code=401,
            detail={"error": "nope", "code": "UNAUTHORIZED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.post("/validate")
    async def _validate(body: _Body):
        return {"ok": True}

    # raise_server_exceptions=False so the 500 handler's response is observable.
    return TestClient(app, raise_server_exceptions=False)


client = _client()


def test_dict_detail_passthrough():
    r = client.get("/dict-detail")
    assert r.status_code == 409
    assert r.json() == {"detail": {"error": "already exists", "code": "TAKEN"}}


def test_string_detail_gets_code():
    r = client.get("/string-detail")
    assert r.status_code == 400
    assert r.json() == {"detail": {"error": "bad thing", "code": "BAD_REQUEST"}}


def test_unhandled_exception_is_500_envelope():
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": {"error": "Internal server error", "code": "INTERNAL_ERROR"}}
    assert "boom-secret-do-not-leak" not in r.text  # no traceback / exc leak


def test_headers_preserved():
    r = client.get("/with-headers")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"
    assert r.json()["detail"]["code"] == "UNAUTHORIZED"


def test_validation_error_is_nested():
    r = client.post("/validate", json={"n": "not-an-int"})
    assert r.status_code == 422
    body = r.json()
    assert set(body["detail"].keys()) == {"error", "code"}
    assert body["detail"]["code"] == "VALIDATION_ERROR"


def test_unknown_route_is_404_envelope():
    r = client.get("/no-such-path")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"
