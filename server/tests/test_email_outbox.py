"""Email outbox (2026-10-20): email_sends mở rộng thành queue DB-backed.

Route chỉ enqueue (không gửi inline) → SMTP fail không 503; row retry/backoff
bởi job `flush-email-outbox` trong scheduler sẵn có (1 uvicorn worker).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.core.models import EmailSend, User
from app.core.security import hash_password
from app.services import email_sends, mailer


@pytest.fixture
def capture(monkeypatch):
    """Fake mailer.send_email; state["ok"]=False → SMTP fail."""
    sent: list[tuple[str, str, str]] = []
    state = {"ok": True}

    async def fake(to, subject, body):
        sent.append((to, subject, body))
        return (state["ok"], None if state["ok"] else "smtp down")

    monkeypatch.setattr(mailer, "send_email", fake)
    return sent, state


async def _user(db_session, email="o@x.io") -> User:
    u = User(email=email, password_hash=hash_password("secret123"))
    db_session.add(u)
    await db_session.commit()
    return u


async def _drain() -> tuple[int, int]:
    """Drain trong session riêng (pattern scheduler) — tránh stale identity map."""
    async with SessionLocal() as session:
        return await email_sends.drain(session)


async def _row(db_session, user_id: int) -> EmailSend:
    # populate_existing: SessionLocal(expire_on_commit=False) → không tự reload
    return await db_session.scalar(
        select(EmailSend)
        .where(EmailSend.user_id == user_id)
        .order_by(EmailSend.id)
        .execution_options(populate_existing=True)
    )


async def _expire_now(db_session, row_id: int) -> None:
    """Backdate next_attempt_at để lần drain sau pick lại row."""
    await db_session.execute(
        update(EmailSend)
        .where(EmailSend.id == row_id)
        .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()


async def test_enqueue_queues_row_without_sending(db_session, capture, monkeypatch):
    sent, _ = capture
    smtp_calls: list[tuple] = []
    monkeypatch.setattr(mailer, "_send_sync", lambda *a, **k: smtp_calls.append(a))
    u = await _user(db_session)

    email_sends.enqueue(db_session, u.id, "verify_code", u.email, "subj", "body text")
    await db_session.commit()

    row = await _row(db_session, u.id)
    assert (row.status, row.attempts) == ("queued", 0)
    assert (row.to_email, row.subject, row.body) == ("o@x.io", "subj", "body text")
    assert sent == [] and smtp_calls == []


async def test_drain_sends_queued_row(db_session, capture):
    sent, _ = capture
    u = await _user(db_session)
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    await db_session.commit()

    assert await _drain() == (1, 0)
    assert sent == [("o@x.io", "s", "b")]
    row = await _row(db_session, u.id)
    assert row.status == "sent" and row.sent_at is not None


async def test_drain_failure_schedules_retry(db_session, capture):
    sent, state = capture
    state["ok"] = False
    u = await _user(db_session)
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    await db_session.commit()
    now = datetime.now(timezone.utc)

    assert await _drain() == (0, 1)
    row = await _row(db_session, u.id)
    assert row.status == "queued" and row.attempts == 1
    assert row.next_attempt_at > now
    assert row.last_error


async def test_three_failures_mark_failed(db_session, capture):
    _, state = capture
    state["ok"] = False
    u = await _user(db_session)
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    await db_session.commit()
    row = await _row(db_session, u.id)

    for _ in range(3):
        await _drain()
        await _expire_now(db_session, row.id)

    row = await _row(db_session, u.id)
    assert row.status == "failed" and row.attempts == 3


async def test_failed_rows_refund_quota(client, db_session, capture):
    """Row failed KHÔNG tính quota + vẫn giữ để audit → resend không 429."""
    u = await _user(db_session, "rf@x.io")
    now = datetime.now(timezone.utc)
    for _ in range(5):
        db_session.add(
            EmailSend(
                user_id=u.id,
                kind="verify_code",
                to_email=u.email,
                subject="s",
                body="b",
                status="failed",
                created_at=now,
            )
        )
    await db_session.commit()

    await email_sends.check_limit(db_session, u.id, "verify_code")  # no raise
    assert (
        await client.post(
            "/api/auth/login", json={"email": "rf@x.io", "password": "secret123"}
        )
    ).status_code == 200
    assert (await client.post("/api/auth/verify/resend")).status_code == 202


async def test_claim_prevents_double_send(db_session, monkeypatch):
    """Claim UPDATE ... WHERE status='queued' commit TRƯỚC send → drain đồng
    thời (nested, session khác) không gửi lại row đang 'sending'."""
    calls: list[str] = []

    async def fake(to, subject, body):
        calls.append(to)
        # concurrent pass trong lúc row đang 'sending'
        assert await _drain() == (0, 0)
        return True, None

    monkeypatch.setattr(mailer, "send_email", fake)
    u = await _user(db_session)
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    await db_session.commit()

    assert await _drain() == (1, 0)
    assert len(calls) == 1

async def test_sent_row_body_redacted(db_session, capture):
    """BLOCKER bảo mật: mã 6 số (verify/reset) không được nằm at-rest trong
    email_sends sau khi gửi — body=None, subject giữ làm audit."""
    sent, _ = capture
    u = await _user(db_session, "red@x.io")
    email_sends.enqueue(
        db_session, u.id, "verify_code", u.email, "Mã xác thực", "Mã: 123456"
    )
    await db_session.commit()

    assert await _drain() == (1, 0)
    assert sent == [("red@x.io", "Mã xác thực", "Mã: 123456")]  # SMTP vẫn nhận body

    row = await _row(db_session, u.id)
    assert row.status == "sent"
    assert row.body is None
    assert row.subject == "Mã xác thực"

async def test_failed_row_body_redacted(db_session, capture):
    """Terminal 'failed' (hết 3 lượt) → body=None, giữ last_error/audit."""
    _, state = capture
    state["ok"] = False
    u = await _user(db_session, "frd@x.io")
    email_sends.enqueue(
        db_session, u.id, "reset_code", u.email, "Đặt lại", "Mã: 654321"
    )
    await db_session.commit()
    row = await _row(db_session, u.id)

    for _ in range(3):
        assert await _drain() == (0, 1)
        await _expire_now(db_session, row.id)  # khỏi chờ backoff

    row = await _row(db_session, u.id)
    assert row.status == "failed" and row.attempts == 3
    assert row.body is None
    assert row.subject == "Đặt lại"
    assert row.last_error

async def test_retry_row_keeps_body(db_session, capture):
    """Retry-queued GIỮ body: lần gửi sau phải đúng nội dung (không data-loss)."""
    sent, state = capture
    state["ok"] = False
    u = await _user(db_session, "rb@x.io")
    email_sends.enqueue(
        db_session, u.id, "verify_code", u.email, "Mã xác thực", "Mã: 111222"
    )
    await db_session.commit()

    assert await _drain() == (0, 1)
    row = await _row(db_session, u.id)
    assert row.status == "queued" and row.body == "Mã: 111222"

    # retry thành công → gửi đúng nội dung, rồi mới redact
    state["ok"] = True
    await _expire_now(db_session, row.id)
    assert await _drain() == (1, 0)
    assert sent[-1] == ("rb@x.io", "Mã xác thực", "Mã: 111222")
    row = await _row(db_session, u.id)
    assert row.status == "sent" and row.body is None

async def test_claim_sets_lease_preventing_reclaim(db_session, monkeypatch):
    """Claim đẩy next_attempt_at = now + _RECLAIM_AFTER (lease deadline) →
    pass thứ 2 thấy row 'sending' còn lease → KHÔNG reclaim, KHÔNG gửi lần 2."""
    calls: list[str] = []
    lease_ok: list[bool] = []
    row_id: list[int] = []

    async def fake(to, subject, body):
        calls.append(to)
        async with SessionLocal() as other:  # == pass đồng thời
            row = await other.scalar(
                select(EmailSend).where(EmailSend.id == row_id[-1])
            )
            lease_ok.append(row.next_attempt_at > datetime.now(timezone.utc))
            assert await email_sends.drain(other) == (0, 0)
        return True, None

    monkeypatch.setattr(mailer, "send_email", fake)
    u = await _user(db_session, "lease@x.io")
    # due từ lâu (vd scheduler chết vài giờ) → chính là ca bug gửi trùng
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    row = await db_session.scalar(select(EmailSend).where(EmailSend.user_id == u.id))
    row_id.append(row.id)
    await db_session.execute(
        update(EmailSend)
        .where(EmailSend.id == row.id)
        .values(next_attempt_at=datetime.now(timezone.utc) - timedelta(hours=3))
    )
    await db_session.commit()

    assert await _drain() == (1, 0)
    assert calls == ["lease@x.io"]
    assert lease_ok == [True]

async def test_stale_sending_row_reclaimed_once(db_session, monkeypatch):
    """Crash giữa send → 'sending' + lease hết hạn → reclaim về 'queued'
    (pass đó chỉ reclaim, pass sau mới gửi)."""
    calls: list[str] = []

    async def fake(to, subject, body):
        calls.append(to)
        return True, None

    monkeypatch.setattr(mailer, "send_email", fake)
    u = await _user(db_session, "stale@x.io")
    email_sends.enqueue(db_session, u.id, "welcome", u.email, "s", "b")
    await db_session.commit()
    row = await _row(db_session, u.id)
    await db_session.execute(
        update(EmailSend)
        .where(EmailSend.id == row.id)
        .values(
            status="sending",
            next_attempt_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    assert await _drain() == (0, 0)  # chỉ reclaim
    assert calls == []
    row = await _row(db_session, u.id)
    assert row.status == "queued"

    assert await _drain() == (1, 0)
    assert calls == ["stale@x.io"]
