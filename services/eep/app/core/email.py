import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        )
        logger.info("Invitation email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send invitation email to %s: %s", to_email, exc)
        raise
