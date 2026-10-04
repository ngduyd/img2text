"""SMTP email delivery (Task 5).

Sync smtplib run via anyio.to_thread so the event loop never blocks on SMTP.
SMTP failures are logged and swallowed: a down mail server must not turn
password-forgot into a 500.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

import anyio

from app.config import settings

logger = logging.getLogger(__name__)

def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    # ponytail: port 465 → implicit TLS, else plain (+STARTTLS when authed);
    # add per-provider config when a real deploy needs it.
    if settings.smtp_port == 465:
        conn = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            context=ssl.create_default_context(),
        )
    else:
        conn = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        if settings.smtp_user:
            conn.starttls(context=ssl.create_default_context())
    with conn:
        if settings.smtp_user:
            conn.login(settings.smtp_user, settings.smtp_pass)
        conn.send_message(msg)

async def send_email(to: str, subject: str, body: str) -> None:
    try:
        await anyio.to_thread.run_sync(_send_sync, to, subject, body)
    except Exception:
        logger.exception("SMTP send failed (to=%s subject=%r)", to, subject)
