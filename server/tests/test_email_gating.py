"""Wave-5 S5 (Lane E): gating — user chưa verify chỉ gọi được exempt API.

403 flat {code:"email_unverified"}. Admin bypass. settings.env=="test"
(conftest) TẮT gating để toàn bộ suite cũ không vỡ; test đây bật lại bằng
monkeypatch.
"""

import pytest

@pytest.fixture
def gating_on(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "env", "dev")

async def test_unverified_403_on_gated_api(client, gating_on):
    r = await client.post(
        "/api/auth/register", json={"email": "g1@x.io", "password": "secret123"}
    )
    assert r.status_code == 201
    r2 = await client.get("/api/auth/me")  # không thuộc exempt list
    assert r2.status_code == 403
    assert r2.json() == {"code": "email_unverified"}

async def test_gated_also_other_api(client, gating_on):
    await client.post(
        "/api/auth/register", json={"email": "g2@x.io", "password": "secret123"}
    )
    assert (await client.get("/api/jobs")).status_code == 403
    assert (await client.get("/api/auth/profile")).status_code in (401, 403, 405)

async def test_exempt_endpoints_work_unverified(client, gating_on):
    # health mount KHÔNG có prefix /api (router health.py) — không qua gate
    assert (await client.get("/healthz")).status_code == 200
    # login/forgot/reset/verify là exempt — không dính 403 gating
    r = await client.post(
        "/api/auth/login", json={"email": "g3@x.io", "password": "secret123"}
    )
    assert r.status_code == 401  # sai credentials, KHÔNG phải 403
    r = await client.post("/api/auth/verify", json={"code": "123456"})
    assert r.status_code == 401  # thiếu cookie, không phải 403
    r = await client.post("/api/auth/verify/resend")
    assert r.status_code == 401
    r = await client.post("/api/auth/password/forgot", json={"email": "g3@x.io"})
    assert r.status_code == 202
    r = await client.post(
        "/api/auth/password/reset", json={"code": "123456", "password": "newsecret1"}
    )
    assert r.status_code == 422

async def test_verified_user_passes_gate(client, gating_on, db_session):
    from sqlalchemy import update
    from app.core.models import User

    await client.post(
        "/api/auth/register", json={"email": "g4@x.io", "password": "secret123"}
    )
    await db_session.execute(update(User).values(is_verified=True))
    await db_session.commit()
    r = await client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["is_verified"] is True

async def test_admin_bypass(admin_client, gating_on):
    r = await admin_client.get("/api/auth/me")  # admin chưa verify vẫn qua
    assert r.status_code == 200 and r.json()["role"] == "admin"

async def test_no_cookie_not_gated(client, gating_on):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401  # 401 thường, không phải 403 gating

async def test_gating_off_in_test_env(client):
    """env=test (conftest) → middleware skip: register xong xài được ngay."""
    await client.post(
        "/api/auth/register", json={"email": "g5@x.io", "password": "secret123"}
    )
    assert (await client.get("/api/auth/me")).status_code == 200
