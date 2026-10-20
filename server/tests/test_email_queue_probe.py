"""Probe: email = DB outbox — route enqueue, scheduler drain gửi.

Trước đây route gửi inline → SMTP down = 503 email_unavailable. Giờ SMTP down
KHÔNG ảnh hưởng HTTP: row nằm `queued`, retry/backoff, quá 3 lần → `failed`
(refund quota, giữ audit) → resend lại được (không 429).

Ngoài scope: TOCTOU check_limit, enumeration timing forgot, exactly-once,
admin UI cho queue.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.models import EmailSend, User
from app.services import email_sends, mailer
from tests.conftest import _REAL_SEND_SYNC


@pytest.fixture
def smtp_down(monkeypatch):
    """Bật SMTP-down: _send_sync thật + closed port (connection refused)."""
    monkeypatch.setattr(mailer, "_send_sync", _REAL_SEND_SYNC)
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)


async def _drain() -> tuple[int, int]:
    async with SessionLocal() as session:
        return await email_sends.drain(session)


async def _rows(db_session, email: str, kind: str | None = None) -> list[EmailSend]:
    user_id = await db_session.scalar(select(User.id).where(User.email == email))
    if user_id is None:
        return []
    # populate_existing: SessionLocal(expire_on_commit=False) → không tự reload
    q = (
        select(EmailSend)
        .where(EmailSend.user_id == user_id)
        .order_by(EmailSend.id)
        .execution_options(populate_existing=True)
    )
    if kind is not None:
        q = q.where(EmailSend.kind == kind)
    return list((await db_session.execute(q)).scalars().all())


async def _force_due(db_session, email: str) -> None:
    """Backdate mọi row queued của user để drain pick lại ngay."""
    user_id = await db_session.scalar(select(User.id).where(User.email == email))
    await db_session.execute(
        update(EmailSend)
        .where(EmailSend.user_id == user_id, EmailSend.status == "queued")
        .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()


async def test_register_smtp_down_still_201_then_refund(client, db_session, smtp_down):
    """SMTP down: register vẫn 201, 2 row queued; drain fail 3 lần → failed
    (refund quota) → resend 202, KHÔNG 429."""
    email = "q1@x.io"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    rows = await _rows(db_session, email)
    assert [row.kind for row in rows] == ["welcome", "verify_code"]
    assert {row.status for row in rows} == {"queued"}
    assert rows[0].to_email == email and rows[0].subject and rows[0].body

    for _ in range(3):  # 3 lần fail → failed
        assert sum(await _drain()) >= 1
        await _force_due(db_session, email)
    assert {row.status for row in await _rows(db_session, email)} == {"failed"}

    assert (
        await client.post(
            "/api/auth/login", json={"email": email, "password": "secret123"}
        )
    ).status_code == 200
    r2 = await client.post("/api/auth/verify/resend")
    assert r2.status_code == 202 and r2.json() == {}


async def test_forgot_smtp_down_202_queued(client, db_session, smtp_down):
    """forgot known + SMTP down → 202 (không 503), row reset_code queued;
    drain fail 3 lần → failed (refund) → forgot lại vẫn 202, không 429."""
    email = "q2@x.io"
    assert (
        await client.post(
            "/api/auth/register", json={"email": email, "password": "secret123"}
        )
    ).status_code == 201
    r = await client.post("/api/auth/password/forgot", json={"email": email})
    assert r.status_code == 202 and r.json() == {}
    rows = await _rows(db_session, email, "reset_code")
    assert [row.status for row in rows] == ["queued"]

    for _ in range(3):
        assert sum(await _drain()) >= 1
        await _force_due(db_session, email)
    assert [row.status for row in await _rows(db_session, email, "reset_code")] == [
        "failed"
    ]

    r2 = await client.post("/api/auth/password/forgot", json={"email": email})
    assert r2.status_code == 202 and r2.json() == {}  # refund → không 429

    r = await client.post("/api/auth/password/forgot", json={"email": "nobody@x.io"})
    assert r.status_code == 202
