"""SMTP email delivery (Task 5).

Sync smtplib run via anyio.to_thread so the event loop never blocks on SMTP.
#9 (spec 2026-10-15): failures are NOT swallowed — send_email returns
(ok, error) and callers (auth routes) decide the HTTP response.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

import anyio

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    # ponytail: port 465 → implicit TLS, else plain (+STARTTLS when authed);
    # add per-provider config when a real deploy needs it.
    # timeout=10: no socket-default hang — unreachable SMTP would pin the
    # anyio.to_thread pool and make known-email forgot hang while unknown
    # returns instant 202 (timing-based user enumeration).
    if settings.smtp_port == 465:
        conn = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            context=ssl.create_default_context(),
            timeout=10,
        )
    else:
        conn = smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=10
        )
        if settings.smtp_user:
            conn.starttls(context=ssl.create_default_context())
    with conn:
        if settings.smtp_user:
            conn.login(settings.smtp_user, settings.smtp_pass)
        conn.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """(True, None) on delivery; (False, error) on SMTP failure — never raises
    (#9: a down mail server surfaces to the caller, not a swallowed log)."""
    try:
        await anyio.to_thread.run_sync(_send_sync, to, subject, body)
    except Exception as exc:
        logger.exception("SMTP send failed (to=%s subject=%r)", to, subject)
        return False, str(exc) or type(exc).__name__
    return True, None
