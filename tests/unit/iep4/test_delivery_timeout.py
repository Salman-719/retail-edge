"""IEP4 email-delivery timeout test.

A wedged SMTP server must never stall the evaluation cycle: aiosmtplib.send must
be called with a bounded timeout. delivery.py only imports aiosmtplib + stdlib
(no `app.*`), so we load it by file path to avoid the cross-service `app`
package-name collision.
"""
import asyncio
import importlib.util
import types
from pathlib import Path

_DELIVERY = (
    Path(__file__).resolve().parents[3]
    / "services" / "iep4_alerts" / "app" / "alerts" / "delivery.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("iep4_delivery_under_test", _DELIVERY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _settings(**over):
    base = dict(
        email_enabled=True,
        environment="production",
        smtp_host="mail.example.com",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        smtp_from="alerts@example.com",
        smtp_timeout_s=10.0,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_smtp_send_has_timeout(monkeypatch):
    mod = _load()
    captured = {}

    async def fake_send(msg, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mod.aiosmtplib, "send", fake_send)

    delivery = mod.EmailDelivery(_settings(smtp_timeout_s=7.5))
    asyncio.run(delivery.send(["ops@example.com"], "Queue building", "body"))

    assert captured.get("timeout") == 7.5


def test_send_skipped_when_email_disabled(monkeypatch):
    mod = _load()
    called = {"n": 0}

    async def fake_send(msg, **kwargs):
        called["n"] += 1

    monkeypatch.setattr(mod.aiosmtplib, "send", fake_send)

    delivery = mod.EmailDelivery(_settings(email_enabled=False))
    asyncio.run(delivery.send(["ops@example.com"], "subj", "body"))

    assert called["n"] == 0  # no SMTP call when delivery is disabled
