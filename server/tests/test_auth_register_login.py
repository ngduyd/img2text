"""Task 3: register/login/me with JWT access cookie."""


async def test_register_201_and_me(client):
    r = await client.post("/api/auth/register", json={"accept_tos": True, "email":"u@x.io","password":"secret123"})
    # P1-1: body {"status":"ok"} — không id/email, không cookie (client tự login)
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    assert "set-cookie" not in r.headers
    await client.post("/api/auth/login", json={"email":"u@x.io","password":"secret123"})
    r2 = await client.get("/api/auth/me")
    assert r2.status_code == 200 and r2.json()["email"] == "u@x.io"


async def test_register_duplicate_identical_body_no_leak(client):
    """P1-1: fresh lẫn duplicate trả body identical — không existence oracle
    (id/email), không cookie cả 2 case."""
    r1 = await client.post("/api/auth/register", json={"accept_tos": True, "email":"d@x.io","password":"secret123"})
    r2 = await client.post("/api/auth/register", json={"accept_tos": True, "email":"d@x.io","password":"secret123"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json() == r2.json() == {"status": "ok"}
    assert "set-cookie" not in r1.headers and "set-cookie" not in r2.headers


async def test_login_wrong_password_401_not_500(client):
    await client.post("/api/auth/register", json={"accept_tos": True, "email":"w@x.io","password":"secret123"})
    r = await client.post("/api/auth/login", json={"email":"w@x.io","password":"wrong-pass"})
    assert r.status_code == 401


async def test_me_without_cookie_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_register_validation_422(client):
    r = await client.post("/api/auth/register", json={"accept_tos": True, "email": "bad", "password": "secret123"})
    assert r.status_code == 422
    r = await client.post("/api/auth/register", json={"accept_tos": True, "email": "s@x.io", "password": "short"})
    assert r.status_code == 422


async def test_login_malformed_stored_hash_401_not_500(client, db_session):
    from app.core.models import User

    db_session.add(User(email="m@x.io", password_hash="not-a-bcrypt-hash"))
    await db_session.commit()
    r = await client.post("/api/auth/login", json={"email": "m@x.io", "password": "secret123"})
    assert r.status_code == 401


async def test_email_case_insensitive(client):
    """Emails normalized to lowercase at the boundary (spec §4); unique
    constraint still catches case-variant duplicates."""
    r = await client.post(
        "/api/auth/register", json={"accept_tos": True, "email": "  Case@X.IO ", "password": "secret123"}
    )
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    r2 = await client.post(
        "/api/auth/login", json={"email": "case@x.io", "password": "secret123"}
    )
    assert r2.status_code == 200 and r2.json()["email"] == "case@x.io"
    dup = await client.post(
        "/api/auth/register", json={"accept_tos": True, "email": "CASE@x.io", "password": "secret123"}
    )
    assert dup.status_code == 201 and dup.json() == {"status": "ok"}  # P1-1: không leak

async def test_register_auto_verifies_when_smtp_missing(
    client, monkeypatch, db_session
):
    """Không có SMTP = không có cách nào verify → tài khoản mới phải dùng được
    ngay (trước đây 403 email_unverified vĩnh viễn)."""
    from sqlalchemy import func, select
    from app.core.config import settings
    from app.core.models import EmailSend, User

    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "auto_verify_email", False)
    r = await client.post(
        "/api/auth/register",
        json={"email": "auto@x.io", "password": "pw-12345678", "accept_tos": True},
    )
    assert r.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "auto@x.io"))
    assert user.is_verified is True
    assert user.ocr_enabled is True          # demo tự phục vụ: OCR bật luôn
    sent = await db_session.scalar(
        select(func.count()).select_from(EmailSend).where(EmailSend.user_id == user.id)
    )
    assert sent == 0                          # không hẹn gửi mail vô nghĩa


async def test_register_keeps_verification_when_smtp_configured(
    client, monkeypatch, db_session
):
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.models import User

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "auto_verify_email", False)
    r = await client.post(
        "/api/auth/register",
        json={"email": "verif@x.io", "password": "pw-12345678", "accept_tos": True},
    )
    assert r.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "verif@x.io"))
    assert user.is_verified is False
    assert user.email_verify_code_hash


async def test_login_rate_limited_per_account(client):
    """Trần theo IP là 60/giờ (NAT dùng chung) nhưng mỗi tài khoản chỉ 10
    lần/15 phút → dò mật khẩu vẫn bị chặn."""
    await client.post(
        "/api/auth/register",
        json={"email": "brute@x.io", "password": "pw-12345678", "accept_tos": True},
    )
    codes = []
    for _ in range(11):
        r = await client.post(
            "/api/auth/login", json={"email": "brute@x.io", "password": "sai-mat-khau"}
        )
        codes.append(r.status_code)
    assert codes[0] == 401
    assert codes[-1] == 429
    assert 429 in codes
