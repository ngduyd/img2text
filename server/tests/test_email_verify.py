"""Wave-5 S5 (Lane E): email verify, reset code, per-kind email limits,
gating. DB: img2text_test@5436 — migration docs/migrations/2026-10-15_email_verify.sql."""

from datetime import datetime, timedelta, timezone
import re

import pytest

async def test_user_defaults_unverified_no_codes(db_session):
    from app.core.models import User

    u = User(email="fresh@x.io", password_hash="x")
    db_session.add(u)
    await db_session.commit()
    assert u.is_verified is False
    assert u.email_verify_code_hash is None
    assert u.email_verify_expires_at is None
    assert u.password_reset_code is None
    assert u.password_reset_expires_at is None

async def test_email_sends_audit_row(db_session):
    from app.core.models import EmailSend, User

    u = User(email="audit@x.io", password_hash="x")
    db_session.add(u)
    await db_session.commit()
    row = EmailSend(user_id=u.id, kind="welcome")
    db_session.add(row)
    await db_session.commit()
    assert row.id is not None
    assert row.kind == "welcome"
    assert isinstance(row.created_at, datetime)

# --- per-kind email limits (app/services/email_sends.py) ---

def _seed(db_session, user_id, kind, offsets):
    """email_sends rows `offsets` seconds ago (oldest first)."""
    from app.core.models import EmailSend

    now = datetime.now(timezone.utc)
    for off in offsets:
        db_session.add(
            EmailSend(user_id=user_id, kind=kind, created_at=now - timedelta(seconds=off))
        )

async def _user(db_session, email="lim@x.io"):
    from app.core.models import User

    u = User(email=email, password_hash="x")
    db_session.add(u)
    await db_session.commit()
    return u

async def test_limit_fresh_user_each_kind_ok(db_session):
    from app.services.email_sends import check_limit

    u = await _user(db_session)
    for kind in ("welcome", "verify_code", "reset_code"):
        await check_limit(db_session, u.id, kind)  # no raise

async def _expect_429(db_session, user_id, kind):
    from app.services.email_sends import EmailLimitExceeded, check_limit

    with pytest.raises(EmailLimitExceeded) as ei:
        await check_limit(db_session, user_id, kind)
    return {"retry_after_seconds": ei.value.retry_after_seconds}

async def test_limit_daily_cap_429(db_session):
    u = await _user(db_session)
    # 5 lần gần nhất trải trong 24h (cũ nhất 20h trước)
    _seed(db_session, u.id, "welcome", [72000, 50000, 30000, 10000, 100])
    await db_session.commit()
    body = await _expect_429(db_session, u.id, "welcome")
    # retry_after = oldest(20h trước) + 24h - now ≈ 4h
    assert 14000 <= body["retry_after_seconds"] <= 14500

async def test_limit_spacing_10min_sends_2_3(db_session):
    u = await _user(db_session)
    _seed(db_session, u.id, "verify_code", [300])  # lần 1: 5 phút trước
    await db_session.commit()
    body = await _expect_429(db_session, u.id, "verify_code")
    assert 290 <= body["retry_after_seconds"] <= 301  # 10p - 5p còn ~300s

async def test_limit_4th_send_needs_1h_gap(db_session):
    u = await _user(db_session)
    # đã 3 lần (#4 tính tiếp): lần gần nhất 30 phút trước → cần 1h
    _seed(db_session, u.id, "reset_code", [10000, 7000, 1800])
    await db_session.commit()
    body = await _expect_429(db_session, u.id, "reset_code")
    assert 1700 <= body["retry_after_seconds"] <= 1801

async def test_limit_4th_send_ok_when_gap_met(db_session):
    from app.services.email_sends import check_limit, record

    u = await _user(db_session)
    _seed(db_session, u.id, "welcome", [20000, 15000, 10000, 7000])  # 4 lần cũ > 1h
    await db_session.commit()
    await check_limit(db_session, u.id, "welcome")  # 5th, gap 7000s > 1h → ok
    record(db_session, u.id, "welcome")
    await db_session.commit()
    from sqlalchemy import func, select
    from app.core.models import EmailSend

    n = await db_session.scalar(
        select(func.count()).select_from(EmailSend).where(EmailSend.user_id == u.id)
    )
    assert n == 5

async def test_limit_kinds_independent(db_session):
    from app.services.email_sends import check_limit

    u = await _user(db_session)
    _seed(db_session, u.id, "welcome", [100, 50, 10, 5, 1])
    await db_session.commit()
    await check_limit(db_session, u.id, "verify_code")  # kind khác → ok

# --- register: welcome + verify-code email, always 201 ---

def _capture():
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))

    return sent, fake

_CODE_RE = re.compile(r"code is:?\s*(\d{6})")

async def test_register_sends_welcome_and_verify_code(client, monkeypatch, db_session):
    from sqlalchemy import select
    from app.core.models import EmailSend, User
    import hashlib

    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r = await client.post(
        "/api/auth/register", json={"email": "new@x.io", "password": "secret123"}
    )
    assert r.status_code == 201
    assert r.json()["is_verified"] is False
    assert [s[0] for s in sent] == ["new@x.io", "new@x.io"]
    code = None
    for _, subject, body in sent:
        m = _CODE_RE.search(body)
        if m:
            code = m.group(1)
    assert code is not None, f"no 6-digit code in emails: {sent!r}"
    user = await db_session.scalar(select(User).where(User.email == "new@x.io"))
    assert user.is_verified is False
    assert user.email_verify_code_hash == hashlib.sha256(code.encode()).hexdigest()
    assert user.email_verify_expires_at is not None
    kinds = (
        await db_session.execute(
            select(EmailSend.kind).where(EmailSend.user_id == user.id).order_by(EmailSend.id)
        )
    ).scalars().all()
    assert kinds == ["welcome", "verify_code"]

async def test_register_duplicate_201_no_leak_no_cookie(client, monkeypatch):
    """S5: luôn 201, không leak tồn tại — không cookie, không email cho
    email đã đăng ký."""
    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r1 = await client.post(
        "/api/auth/register", json={"email": "dup@x.io", "password": "secret123"}
    )
    assert r1.status_code == 201 and r1.json()["id"] != 0
    n_first = len(sent)
    r2 = await client.post(
        "/api/auth/register", json={"email": "dup@x.io", "password": "secret123"}
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == 0  # decoy — không trả id thật
    assert "set-cookie" not in r2.headers
    assert len(sent) == n_first  # không gửi thêm email

async def test_register_smtp_down_still_201(client, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.mailer._send_sync", boom)
    r = await client.post(
        "/api/auth/register", json={"email": "down@x.io", "password": "secret123"}
    )
    assert r.status_code == 201
