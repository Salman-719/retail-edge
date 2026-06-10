"""EEP resilience-helper tests: per-boundary timeouts + the reads-only retry.

resilience.py imports only tenacity/redis + (lazily) botocore — no `app.*` — so
we load it by file path to avoid the cross-service `app` package-name collision.
"""
import importlib.util
from pathlib import Path

import pytest

_RES = (
    Path(__file__).resolve().parents[3] / "services" / "eep" / "app" / "core" / "resilience.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("eep_resilience_under_test", _RES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


res = _load()


def test_default_timeout_values():
    assert res.DB_STATEMENT_TIMEOUT_S == 30.0
    assert res.REDIS_SOCKET_TIMEOUT_S == 2.0
    assert res.REDIS_CONNECT_TIMEOUT_S == 2.0
    assert res.SMTP_TIMEOUT_S == 10.0
    assert res.S3_MAX_ATTEMPTS == 3


def test_s3_config_has_timeouts_and_native_retries():
    cfg = res.s3_config()
    assert cfg.connect_timeout == res.S3_CONNECT_TIMEOUT_S
    assert cfg.read_timeout == res.S3_READ_TIMEOUT_S
    assert cfg.retries["max_attempts"] == res.S3_MAX_ATTEMPTS
    assert cfg.retries["mode"] == "standard"


def test_retry_reads_retries_transient_then_succeeds():
    calls = {"n": 0}

    @res.retry_reads
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3  # initial try + 2 retries


def test_retry_reads_gives_up_and_reraises_original():
    @res.retry_reads
    def always_down():
        raise ConnectionError("redis unreachable")

    # reraise=True → the ORIGINAL exception, not tenacity's RetryError.
    with pytest.raises(ConnectionError):
        always_down()


def test_retry_reads_does_not_retry_nontransient():
    calls = {"n": 0}

    @res.retry_reads
    def logic_bug():
        calls["n"] += 1
        raise ValueError("not a transient error")

    with pytest.raises(ValueError):
        logic_bug()
    assert calls["n"] == 1  # raised on first attempt, never retried
