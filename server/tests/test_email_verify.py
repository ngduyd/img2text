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
    from app.services.email_sends import check_limit, enqueue

    u = await _user(db_session)
    _seed(db_session, u.id, "welcome", [20000, 15000, 10000, 7000])  # 4 lần cũ > 1h
    await db_session.commit()
    await check_limit(db_session, u.id, "welcome")  # 5th, gap 7000s > 1h → ok
    enqueue(db_session, u.id, "welcome", u.email, "s", "b")
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

# --- register: welcome + verify-code email; SMTP down → 503 (#9) ---

async def _flush() -> None:
    """Outbox: route chỉ enqueue — drain để fake send_email nhận được mail."""
    from app.core.db import SessionLocal
    from app.services import email_sends

    async with SessionLocal() as session:
        await email_sends.drain(session)

def _capture():
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))
        return (True, None)  # mailer contract #9: (ok, error)

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
    assert r.json() == {"status": "ok"}  # P1-1: body bằng nhau 2 case
    await _flush()  # outbox: route chỉ enqueue
    assert [s[0] for s in sent] == ["new@x.io", "new@x.io"]
    code = None
    for _, subject, body in sent:
        m = _CODE_RE.search(body)
        if m:
            code = m.group(1)
    assert code is not None, f"no 6-digit code in emails: {sent!r}"
    user = await db_session.scalar(select(User).where(User.email == "new@x.io"))
    assert user.is_verified is False
    from app.core.security import hash_email_code

    # P1-3: hash per-user = sha256(f"{email}:{code}:{app_secret}")
    assert user.email_verify_code_hash == hash_email_code("new@x.io", code)
    assert user.email_verify_expires_at is not None
    kinds = (
        await db_session.execute(
            select(EmailSend.kind).where(EmailSend.user_id == user.id).order_by(EmailSend.id)
        )
    ).scalars().all()
    assert kinds == ["welcome", "verify_code"]

async def test_register_duplicate_identical_body(client, monkeypatch):
    """P1-1: luôn 201 — fresh lẫn duplicate body identical {"status":"ok"},
    không cookie, không email cho email đã đăng ký."""
    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r1 = await client.post(
        "/api/auth/register", json={"email": "dup@x.io", "password": "secret123"}
    )
    assert r1.status_code == 201 and r1.json() == {"status": "ok"}
    assert "set-cookie" not in r1.headers
    await _flush()
    n_first = len(sent)
    r2 = await client.post(
        "/api/auth/register", json={"email": "dup@x.io", "password": "secret123"}
    )
    assert r2.status_code == 201 and r2.json() == {"status": "ok"}
    assert "set-cookie" not in r2.headers
    await _flush()
    assert len(sent) == n_first  # không enqueue thêm email

async def test_register_smtp_down_still_201_queued(client, monkeypatch, db_session):
    """Outbox: SMTP down không còn 503 — register 201, 2 row queued cho drain."""
    from sqlalchemy import select
    from app.core.models import EmailSend

    def boom(*a, **kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.mailer._send_sync", boom)
    r = await client.post(
        "/api/auth/register", json={"email": "down@x.io", "password": "secret123"}
    )
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    kinds = (
        await db_session.execute(
            select(EmailSend.kind, EmailSend.status).order_by(EmailSend.id)
        )
    ).all()
    assert [tuple(k) for k in kinds] == [
        ("welcome", "queued"),
        ("verify_code", "queued"),
    ]
    # user đã commit TRƯỚC khi gửi → duplicate register vẫn 201 (body cũ)
    dup = await client.post(
        "/api/auth/register", json={"email": "down@x.io", "password": "secret123"}
    )
    assert dup.status_code == 201 and dup.json() == {"status": "ok"}

# --- POST /api/auth/verify + /verify/resend ---

async def _register_with_code(client, monkeypatch, email="v@x.io"):
    """Register + login (P1-1: register không cookie) + trả về mã 6 số
    từ email verify vừa capture."""
    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201
    await _flush()  # outbox: route chỉ enqueue
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "secret123"}
    )
    assert login.status_code == 200
    for _, _, body in sent:
        m = _CODE_RE.search(body)
        if m:
            return m.group(1)
    raise AssertionError(f"no code in {sent!r}")

async def test_verify_correct_code_200(client, monkeypatch, db_session):
    from sqlalchemy import select
    from app.core.models import User

    code = await _register_with_code(client, monkeypatch)
    r = await client.post("/api/auth/verify", json={"code": code})
    assert r.status_code == 200 and r.json() == {}
    r2 = await client.get("/api/auth/me")
    assert r2.json()["is_verified"] is True
    user = await db_session.scalar(select(User).where(User.email == "v@x.io"))
    assert user.email_verify_code_hash is None  # single-use: xóa sau khi dùng

async def test_verify_wrong_code_422(client, monkeypatch):
    await _register_with_code(client, monkeypatch)
    r = await client.post("/api/auth/verify", json={"code": "000000"})
    assert r.status_code == 422

async def test_verify_expired_code_422(client, monkeypatch, db_session):
    """Code ĐÚNG nhưng hết hạn → 422 (tách bạch với lỗi sai mã)."""
    import hashlib as _h
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.core.models import User

    await _register_with_code(client, monkeypatch)
    code = "123456"
    from app.core.security import hash_email_code

    await db_session.execute(
        update(User).values(
            email_verify_code_hash=hash_email_code("v@x.io", code),
            email_verify_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db_session.commit()
    r = await client.post("/api/auth/verify", json={"code": code})
    assert r.status_code == 422

async def test_verify_requires_auth(client):
    r = await client.post("/api/auth/verify", json={"code": "123456"})
    assert r.status_code == 401

def _code_from(body: str) -> str:
    m = _CODE_RE.search(body)
    assert m, f"no code in email body: {body!r}"
    return m.group(1)

async def test_resend_new_code_overwrites_old(client, monkeypatch, db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.core.models import EmailSend

    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    r = await client.post(
        "/api/auth/register", json={"email": "rs@x.io", "password": "secret123"}
    )
    assert r.status_code == 201
    await _flush()  # outbox: route chỉ enqueue
    # P1-1: register không cookie → login để có session cho resend
    assert (
        await client.post(
            "/api/auth/login", json={"email": "rs@x.io", "password": "secret123"}
        )
    ).status_code == 200
    old = _code_from(sent[1][2])
    # spacing: verify email của register là send #1 → backdate 11 phút để
    # resend (#2, gap ≥10p) qua limit
    await db_session.execute(
        update(EmailSend)
        .where(EmailSend.kind == "verify_code")
        .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=11))
    )
    await db_session.commit()
    r = await client.post("/api/auth/verify/resend")
    assert r.status_code == 202 and r.json() == {}
    await _flush()
    new = _code_from(sent[-1][2])
    assert new != old  # single active code: resend ghi đè
    assert (
        await client.post("/api/auth/verify", json={"code": old})
    ).status_code == 422
    assert (
        await client.post("/api/auth/verify", json={"code": new})
    ).status_code == 200

async def test_resend_already_verified_400(client, monkeypatch, db_session):
    """P2: resend khi đã verified → 400 {code:already_verified}, KHÔNG gửi
    email (không dùng resend làm kênh email-bomb)."""
    from sqlalchemy import select
    from app.core.models import User

    sent, fake = _capture()
    monkeypatch.setattr("app.services.mailer.send_email", fake)
    code = await _register_with_code(client, monkeypatch, email="av@x.io")
    assert (await client.post("/api/auth/verify", json={"code": code})).status_code == 200
    n = len(sent)
    r = await client.post("/api/auth/verify/resend")
    assert r.status_code == 400 and r.json() == {"code": "already_verified"}
    assert len(sent) == n  # không gửi thêm email
    user = await db_session.scalar(select(User).where(User.email == "av@x.io"))
    assert user.email_verify_code_hash is None  # không sinh code mới

async def test_eleven_wrong_verify_codes_429(client, monkeypatch):
    """P2: 11 lần verify sai mã liên tiếp → rate limiter cắt (429), không
    rò rỉ 200/422 vĩnh viễn."""
    await _register_with_code(client, monkeypatch, email="br@x.io")
    statuses = []
    for _ in range(11):
        r = await client.post("/api/auth/verify", json={"code": "000000"})
        statuses.append(r.status_code)
    assert set(statuses) <= {422, 429}
    assert 429 in statuses
    assert statuses[-1] == 429  # các lần sau bị chặn tiếp

async def test_resend_over_email_limit_429(client, monkeypatch, db_session):
    """verify_code đã gửi 5 lần/24h → resend 429 flat body email_limit."""
    from sqlalchemy import select
    from app.core.models import User

    await _register_with_code(client, monkeypatch, email="rl@x.io")
    u = await db_session.scalar(select(User).where(User.email == "rl@x.io"))
    _seed(db_session, u.id, "verify_code", [100, 50, 10, 5, 1])
    await db_session.commit()
    r = await client.post("/api/auth/verify/resend")
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "email_limit" and body["retry_after_seconds"] >= 1
