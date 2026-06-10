"""Single end-to-end smoke test against the LIVE deployed EEP.

The brief's one "E2E hitting the live deployed URL" — catches deployment bugs the
unit/integration tiers cannot. Gated by tests/conftest.py: runs only with
`--cloud` and CLOUD_URL set, otherwise skipped, so the default suite stays green.

  CLOUD_URL=https://eep.example.com pytest tests/e2e/test_cloud.py --cloud -v
"""
import os

import httpx
import pytest

pytestmark = pytest.mark.cloud

CLOUD_URL = os.environ.get("CLOUD_URL", "").rstrip("/")
_TIMEOUT = float(os.environ.get("CLOUD_E2E_TIMEOUT_S", "10"))


def test_health_ok():
    """The deployment is up and serving."""
    r = httpx.get(f"{CLOUD_URL}/health", timeout=_TIMEOUT)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_unknown_route_uses_error_envelope():
    """A 404 comes back as the canonical {detail:{error,code}} envelope, not a bare body."""
    r = httpx.get(f"{CLOUD_URL}/no-such-endpoint-xyz", timeout=_TIMEOUT)
    assert r.status_code == 404
    detail = r.json().get("detail")
    assert isinstance(detail, dict) and "error" in detail and "code" in detail


def test_protected_read_requires_auth_not_500():
    """An unauthenticated read is rejected cleanly (401/403), never a 500."""
    r = httpx.get(f"{CLOUD_URL}/stores", timeout=_TIMEOUT)
    assert r.status_code in (401, 403)
    detail = r.json().get("detail")
    assert isinstance(detail, dict) and "code" in detail
