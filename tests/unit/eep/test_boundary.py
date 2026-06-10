"""EEP boundary-hardening tests.

R3 — optional S3 presign enrichment degrades to None on failure (a bad/unsignable
key must never 500 the config/analytics read), and never fabricates a URL.
Imported via the eep conftest's services/eep path shim.
"""
from app.core import s3_client


def test_safe_presign_none_or_empty_key_returns_none():
    assert s3_client.safe_presign_public(None) is None
    assert s3_client.safe_presign_public("") is None


def test_safe_presign_degrades_to_none_on_error(monkeypatch):
    def _boom(key, expiry=3600):
        raise RuntimeError("MinIO down / bad key")

    monkeypatch.setattr(s3_client, "generate_presigned_url_public", _boom)
    # Enrichment failure → None, not an exception.
    assert s3_client.safe_presign_public("frames/x.jpg") is None


def test_safe_presign_returns_url_on_success(monkeypatch):
    monkeypatch.setattr(
        s3_client, "generate_presigned_url_public", lambda key, expiry=3600: f"https://signed/{key}"
    )
    assert s3_client.safe_presign_public("frames/x.jpg") == "https://signed/frames/x.jpg"
