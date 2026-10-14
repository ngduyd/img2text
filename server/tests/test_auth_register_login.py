"""Task 3: register/login/me with JWT access cookie."""


async def test_register_201_and_me(client):
    r = await client.post("/api/auth/register", json={"email":"u@x.io","password":"secret123"})
    # P1-1: body {"status":"ok"} — không id/email, không cookie (client tự login)
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    assert "set-cookie" not in r.headers
    await client.post("/api/auth/login", json={"email":"u@x.io","password":"secret123"})
    r2 = await client.get("/api/auth/me")
    assert r2.status_code == 200 and r2.json()["email"] == "u@x.io"


async def test_register_duplicate_identical_body_no_leak(client):
    """P1-1: fresh lẫn duplicate trả body identical — không existence oracle
    (id/email), không cookie cả 2 case."""
    r1 = await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    r2 = await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json() == r2.json() == {"status": "ok"}
    assert "set-cookie" not in r1.headers and "set-cookie" not in r2.headers


async def test_login_wrong_password_401_not_500(client):
    await client.post("/api/auth/register", json={"email":"w@x.io","password":"secret123"})
    r = await client.post("/api/auth/login", json={"email":"w@x.io","password":"wrong-pass"})
    assert r.status_code == 401


async def test_me_without_cookie_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_register_validation_422(client):
    r = await client.post("/api/auth/register", json={"email": "bad", "password": "secret123"})
    assert r.status_code == 422
    r = await client.post("/api/auth/register", json={"email": "s@x.io", "password": "short"})
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
        "/api/auth/register", json={"email": "  Case@X.IO ", "password": "secret123"}
    )
    assert r.status_code == 201 and r.json() == {"status": "ok"}
    r2 = await client.post(
        "/api/auth/login", json={"email": "case@x.io", "password": "secret123"}
    )
    assert r2.status_code == 200 and r2.json()["email"] == "case@x.io"
    dup = await client.post(
        "/api/auth/register", json={"email": "CASE@x.io", "password": "secret123"}
    )
    assert dup.status_code == 201 and dup.json() == {"status": "ok"}  # P1-1: không leak
