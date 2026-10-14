"""Wave-5 S5 (Lane E): forgot/reset = mã 6 số TTL 5p (hash), thay token-link.

Ruling R2 cũ (regex token khỏi email) đổi theo spec: email chứa mã 6 số;
tests extract mã bằng regex rồi POST /api/auth/password/reset {code, password}.
"""

import re
from datetime import datetime, timedelta, timezone

_CODE_RE = re.compile(r"code is:?\s*(\d{6})")

def _capture():
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))

    return sent, fake

def _code_from(body: str) -> str:
    m = _CODE_RE.search(body)
    assert m, f"no code in email body: {body!r}"
    return m.group(1)

async def _register(client, monkeypatch, email="r@x.io"):
    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201
    return sent

async def test_forgot_unknown_email_202_no_send(client, monkeypatch):
    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r = await client.post("/api/auth/password/forgot", json={"email": "ghost@x.io"})
    assert r.status_code == 202 and r.json() == {}
    assert sent == []

async def test_forgot_known_email_202_code_email(client, monkeypatch, db_session):
    from sqlalchemy import select
    from app.core.models import EmailSend, User

    sent = await _register(client, monkeypatch)
    n_first = len(sent)
    r = await client.post("/api/auth/password/forgot", json={"email": "r@x.io"})
    assert r.status_code == 202 and r.json() == {}
    to, subject, body = sent[-1]
    assert to == "r@x.io"
    code = _code_from(body)
    assert len(code) == 6 and code.isdigit()
    assert "token=" not in body  # S5: bỏ link-token
    user = await db_session.scalar(select(User).where(User.email == "r@x.io"))
    import hashlib

    assert user.password_reset_code == hashlib.sha256(code.encode()).hexdigest()
    assert user.password_reset_expires_at is not None
    kinds = (
        await db_session.execute(
            select(EmailSend.kind)
            .where(EmailSend.user_id == user.id, EmailSend.kind == "reset_code")
        )
    ).scalars().all()
    assert kinds == ["reset_code"]
    assert len(sent) == n_first + 1

async def test_reset_with_code_changes_password(client, monkeypatch):
    sent = await _register(client, monkeypatch, email="q@x.io")
    await client.post("/api/auth/login", json={"email": "q@x.io", "password": "secret123"})
    assert client.cookies.get("refresh")  # có refresh để revoke
    await client.post("/api/auth/password/forgot", json={"email": "q@x.io"})
    code = _code_from(sent[-1][2])
    r = await client.post(
        "/api/auth/password/reset", json={"code": code, "password": "newsecret1"}
    )
    assert r.status_code == 200
    # single-use: code đã xóa → reset lại 422
    r2 = await client.post(
        "/api/auth/password/reset", json={"code": code, "password": "another99"}
    )
    assert r2.status_code == 422
    assert (await client.post("/api/auth/refresh")).status_code == 401  # revoked
    assert (
        await client.post("/api/auth/login", json={"email": "q@x.io", "password": "newsecret1"})
    ).status_code == 200
    assert (
        await client.post("/api/auth/login", json={"email": "q@x.io", "password": "secret123"})
    ).status_code == 401

async def test_reset_wrong_code_422(client, monkeypatch):
    await _register(client, monkeypatch)
    r = await client.post(
        "/api/auth/password/reset", json={"code": "000000", "password": "newsecret1"}
    )
    assert r.status_code == 422

async def test_reset_expired_code_422(client, monkeypatch, db_session):
    from sqlalchemy import update
    from app.core.models import User

    sent = await _register(client, monkeypatch)
    await client.post("/api/auth/password/forgot", json={"email": "r@x.io"})
    code = _code_from(sent[-1][2])
    await db_session.execute(
        update(User).values(
            password_reset_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    )
    await db_session.commit()
    r = await client.post(
        "/api/auth/password/reset", json={"code": code, "password": "newsecret1"}
    )
    assert r.status_code == 422

async def test_forgot_over_email_limit_429(client, monkeypatch, db_session):
    from sqlalchemy import select
    from app.core.models import User
    from tests.test_email_verify import _seed

    sent = await _register(client, monkeypatch, email="rl@x.io")
    n = len(sent)
    user = await db_session.scalar(select(User).where(User.email == "rl@x.io"))
    _seed(db_session, user.id, "reset_code", [100, 50, 10, 5, 1])
    await db_session.commit()
    r = await client.post("/api/auth/password/forgot", json={"email": "rl@x.io"})
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "email_limit" and body["retry_after_seconds"] >= 1
    assert len(sent) == n  # check TRƯỚC enqueue — không gửi

async def test_forgot_smtp_failure_still_202(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.mailer._send_sync", boom)
    await _register(client, monkeypatch, email="f@x.io")
    r = await client.post("/api/auth/password/forgot", json={"email": "f@x.io"})
    assert r.status_code == 202
