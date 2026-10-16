"""#9 (spec 2026-10-15): auth email routes trả 503 khi SMTP down.

503 flat {code:"email_unavailable", retry_after_seconds:300} — phân biệt với
429 email_limit (rate limit) và 202 (gửi thành công). Register tạo user
trước → test resend-503 seed user trực tiếp (không qua register email flow).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.models import EmailSend, User
from app.core.security import hash_password
from app.services import mailer
from tests.conftest import _REAL_SEND_SYNC

_SMTP_DOWN = {"smtp_host": "127.0.0.1", "smtp_port": 1}


def _smtp_down(monkeypatch):
    # _send_sync thật + closed port = connection refused thật, không network
    monkeypatch.setattr(mailer, "_send_sync", _REAL_SEND_SYNC)
    for key, value in _SMTP_DOWN.items():
        monkeypatch.setattr(settings, key, value)


async def test_verify_resend_returns_503_on_smtp_failure(
    client, db_session, monkeypatch
):
    db_session.add(
        User(email="a@b.c", password_hash=hash_password("secret123"))
    )
    await db_session.commit()
    r = await client.post(
        "/api/auth/login", json={"email": "a@b.c", "password": "secret123"}
    )
    assert r.status_code == 200
    _smtp_down(monkeypatch)
    resp = await client.post("/api/auth/verify/resend")
    assert resp.status_code == 503
    assert resp.json() == {"code": "email_unavailable", "retry_after_seconds": 300}


async def test_verify_resend_still_202_when_mail_flows(client, db_session):
    db_session.add(
        User(email="ok@b.c", password_hash=hash_password("secret123"))
    )
    await db_session.commit()
    r = await client.post(
        "/api/auth/login", json={"email": "ok@b.c", "password": "secret123"}
    )
    assert r.status_code == 200
    # conftest `_smtp_offline` no-op _send_sync → gửi "thành công"
    resp = await client.post("/api/auth/verify/resend")
    assert resp.status_code == 202 and resp.json() == {}


async def test_resend_limit_still_429_before_send(client, db_session, monkeypatch):
    """Distinguish: rate limit (429 email_limit) checked TRƯỚC send — SMTP
    down không được biến limit thành 503."""
    db_session.add(
        User(email="rl2@b.c", password_hash=hash_password("secret123"))
    )
    await db_session.commit()
    r = await client.post(
        "/api/auth/login", json={"email": "rl2@b.c", "password": "secret123"}
    )
    assert r.status_code == 200
    now = datetime.now(timezone.utc)
    db_session.add(
        EmailSend(
            user_id=(
                await db_session.scalar(select(User).where(User.email == "rl2@b.c"))
            ).id,
            kind="verify_code",
            created_at=now - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    _smtp_down(monkeypatch)
    resp = await client.post("/api/auth/verify/resend")
    assert resp.status_code == 429
    assert resp.json()["code"] == "email_limit"


# --- #11 (spec 2026-10-15): bcrypt 72-byte cap at API boundary ---

async def test_register_rejects_password_over_72_bytes(client):
    resp = await client.post(
        "/api/auth/register", json={"email": "a@b.c", "password": "x" * 73}
    )
    assert resp.status_code == 400
    assert resp.json() == {"code": "password_too_long", "max_bytes": 72}

async def test_password_reset_rejects_over_72_bytes(client):
    """Length check TRƯỚC code claim → 400 kể cả code sai (spec expects
    400, không phải 422)."""
    resp = await client.post(
        "/api/auth/password/reset",
        json={"email": "a@b.c", "code": "123456", "password": "x" * 73},
    )
    assert resp.status_code == 400
    assert resp.json() == {"code": "password_too_long", "max_bytes": 72}
