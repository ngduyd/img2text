"""#9 (spec 2026-10-15): send_email surfaces SMTP failure as (False, error).

Conftest autouse `_smtp_offline` no-ops `mailer._send_sync` (hermetic suite —
`send_email` now surfaces, tests must not hit the network); the failure test
restores the REAL `_send_sync` and points it at a closed port.
"""

from tests.conftest import _REAL_SEND_SYNC

from app.core.config import settings
from app.services import mailer


async def test_send_email_returns_failure_on_smtp_down(monkeypatch):
    monkeypatch.setattr(mailer, "_send_sync", _REAL_SEND_SYNC)
    # 127.0.0.1:1 = deterministic connection-refused (offline stand-in for
    # the spec's unreachable-host)
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)
    ok, err = await mailer.send_email("test@example.com", "subj", "body")
    assert ok is False
    assert err is not None


async def test_send_email_returns_success_on_delivery(monkeypatch):
    seen: list[tuple] = []

    def fake_send_sync(to, subject, body):
        seen.append((to, subject, body))

    monkeypatch.setattr(mailer, "_send_sync", fake_send_sync)
    ok, err = await mailer.send_email("test@example.com", "subj", "body")
    assert (ok, err) == (True, None)
    assert seen == [("test@example.com", "subj", "body")]
