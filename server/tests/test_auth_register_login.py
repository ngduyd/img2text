"""Task 3: register/login/me with JWT access cookie."""


async def test_register_201_and_me(client):
    r = await client.post("/api/auth/register", json={"email":"u@x.io","password":"secret123"})
    assert r.status_code == 201
    body = r.json(); assert body["role"] == "user" and body["ocr_enabled"] is False
    r2 = await client.get("/api/auth/me")
    assert r2.status_code == 200 and r2.json()["email"] == "u@x.io"


async def test_register_duplicate_409(client):
    await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    r = await client.post("/api/auth/register", json={"email":"d@x.io","password":"secret123"})
    assert r.status_code == 409


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
    from app.models import User

    db_session.add(User(email="m@x.io", password_hash="not-a-bcrypt-hash"))
    await db_session.commit()
    r = await client.post("/api/auth/login", json={"email": "m@x.io", "password": "secret123"})
    assert r.status_code == 401
