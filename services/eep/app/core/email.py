import logging
import uuid as _uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate

import aiosmtplib
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.resilience import SMTP_TIMEOUT_S

logger = logging.getLogger(__name__)


# Owner (stores.created_by) + members with the receive_notifications permission.
_SHIFT_ALERT_RECIPIENTS = text("""
    SELECT u.email FROM users u
    JOIN store_members sm ON sm.user_id = u.id
    JOIN store_member_permissions smp ON smp.store_member_id = sm.id
    WHERE sm.store_id = :sid
      AND smp.permission = 'receive_notifications'
      AND smp.granted = TRUE
    UNION
    SELECT u.email FROM users u
    JOIN stores s ON s.created_by = u.id
    WHERE s.id = :sid
""")


async def send_shift_failure_alert(store_id, shift_date, failed_step: str, error_msg: str) -> None:
    """Notify the store owner + managers that the end-of-shift closing sequence
    failed and the analytics job was not started. Plain text. SMTP-optional:
    when SMTP is not configured (dev), the alert is logged and skipped."""
    sid = _uuid.UUID(store_id) if isinstance(store_id, str) else store_id
    async with AsyncSessionLocal() as db:
        store_name = (await db.execute(
            text("SELECT name FROM stores WHERE id = :sid"), {"sid": sid})).scalar() or str(store_id)
        rows = (await db.execute(_SHIFT_ALERT_RECIPIENTS, {"sid": sid})).fetchall()
    recipients = [r[0] for r in rows if r[0]]

    body = (
        "The end-of-shift closing sequence failed and the analytics job was NOT started.\n\n"
        f"Store: {store_name}\n"
        f"Shift date: {shift_date}\n"
        f"Failed step: {failed_step}\n"
        f"Error: {error_msg}\n"
    )
    if not recipients or not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning(
            "Shift failure alert (email skipped — recipients=%d, smtp_configured=%s) "
            "store=%s step=%s: %s",
            len(recipients), bool(settings.SMTP_HOST and settings.SMTP_USER),
            store_id, failed_step, error_msg,
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[RetailVision] End-of-shift analytics FAILED — {store_name}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg["Message-ID"] = make_msgid(domain="retailvision.ai")
    msg["Date"] = formatdate(localtime=False)
    msg.attach(MIMEText(body, "plain"))
    try:
        await aiosmtplib.send(
            msg, hostname=settings.SMTP_HOST, port=settings.SMTP_PORT,
            username=settings.SMTP_USER, password=settings.SMTP_PASSWORD, start_tls=True,
            timeout=SMTP_TIMEOUT_S,
        )
        logger.info("Shift failure alert sent to %d recipient(s) store=%s", len(recipients), store_id)
    except Exception as exc:
        logger.error("Failed to send shift failure alert store=%s: %s", store_id, exc)


async def send_invitation_email(to_email: str, store_name: str, slug: str, token: str) -> None:
    accept_url = f"http://localhost:5173/store/{slug}/accept-invite?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"You're invited to join {store_name} on RetailVision AI"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Message-ID"] = make_msgid(domain="retailvision.ai")
    msg["Date"] = formatdate(localtime=False)

    text = (
        f"You've been invited to join {store_name} on RetailVision AI.\n\n"
        f"Click the link below to accept your invitation:\n{accept_url}\n\n"
        f"This invitation expires in 3 days."
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#1B3A5C">You're invited to RetailVision AI</h2>
      <p>You've been invited to join <strong>{store_name}</strong>.</p>
      <a href="{accept_url}"
         style="display:inline-block;margin:16px 0;padding:10px 24px;
                background:#1B3A5C;color:#fff;border-radius:8px;
                text-decoration:none;font-weight:600">
        Accept Invitation
      </a>
      <p style="color:#888;font-size:12px">This invitation expires in 3 days.<br>
        If you weren't expecting this, you can safely ignore it.</p>
    </div>
    """

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
            timeout=SMTP_TIMEOUT_S,
        )
        logger.info("Invitation email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send invitation email to %s: %s", to_email, exc)


async def send_password_reset_email(to_email: str, token: str) -> None:
    reset_url = f"http://localhost:5173/reset-password?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your RetailVision AI password"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Message-ID"] = make_msgid(domain="retailvision.ai")
    msg["Date"] = formatdate(localtime=False)

    text = (
        f"You requested a password reset for your RetailVision AI account.\n\n"
        f"Click the link below to set a new password:\n{reset_url}\n\n"
        f"This link expires in 1 hour. If you did not request this, you can safely ignore it."
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#1B3A5C">Reset your password</h2>
      <p>You requested a password reset for your RetailVision AI account.</p>
      <a href="{reset_url}"
         style="display:inline-block;margin:16px 0;padding:10px 24px;
                background:#1B3A5C;color:#fff;border-radius:8px;
                text-decoration:none;font-weight:600">
        Reset Password
      </a>
      <p style="color:#888;font-size:12px">This link expires in 1 hour.<br>
        If you didn't request this, you can safely ignore it.</p>
    </div>
    """

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
            timeout=SMTP_TIMEOUT_S,
        )
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send password reset email to %s: %s", to_email, exc)
