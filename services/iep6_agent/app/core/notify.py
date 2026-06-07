"""Email delivery for insights/alerts (no-op if SMTP isn't configured)."""
import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

log = logging.getLogger(__name__)


async def send_email(subject: str, body: str, to: str) -> bool:
    if not (settings.SMTP_HOST and settings.SMTP_USER and to):
        log.info("SMTP not configured — skipping email: %s", subject)
        return False
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        await aiosmtplib.send(
            msg, hostname=settings.SMTP_HOST, port=settings.SMTP_PORT,
            username=settings.SMTP_USER, password=settings.SMTP_PASSWORD, start_tls=True,
        )
        return True
    except Exception:
        log.exception("email send failed: %s", subject)
        return False
