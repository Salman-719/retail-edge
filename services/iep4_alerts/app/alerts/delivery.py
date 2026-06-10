"""Email delivery via aiosmtplib (never blocking smtplib).

Sent only on the first FIRING transition. In development (or when SMTP is not
configured) delivery is logged and skipped so the daemon runs without a mail
server.
"""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

logger = logging.getLogger(__name__)


class EmailDelivery:
    def __init__(self, settings) -> None:
        self._s = settings

    async def send(self, recipients: list[str], subject: str, body: str) -> None:
        if not recipients:
            return
        if not self._s.email_enabled:
            logger.info(
                "Email skipped (environment=%s, smtp_host=%r) — would notify %s: %s",
                self._s.environment, self._s.smtp_host, recipients, subject,
            )
            return

        msg = EmailMessage()
        msg["From"] = self._s.smtp_from or self._s.smtp_user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)

        # Bounded send so a wedged SMTP server cannot stall the evaluation cycle.
        await aiosmtplib.send(
            msg,
            hostname=self._s.smtp_host,
            port=self._s.smtp_port,
            username=self._s.smtp_user or None,
            password=self._s.smtp_password or None,
            start_tls=self._s.smtp_port == 587,
            timeout=self._s.smtp_timeout_s,
        )
        logger.info("Alert email sent to %d recipient(s): %s", len(recipients), subject)
