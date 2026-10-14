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
    # P1-1: register không cookie → login để gate nhận diện user
    assert (
        await client.post(
            "/api/auth/login", json={"email": "g1@x.io", "password": "secret123"}
        )
    ).status_code == 200
    r2 = await client.get("/api/auth/me")  # không thuộc exempt list
    assert r2.status_code == 403
    assert r2.json() == {"code": "email_unverified"}

async def test_gated_also_other_api(client, gating_on):
    await client.post(
        "/api/auth/register", json={"email": "g2@x.io", "password": "secret123"}
    )
    await client.post(
        "/api/auth/login", json={"email": "g2@x.io", "password": "secret123"}
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
        "/api/auth/password/reset",
        json={"email": "g3@x.io", "code": "123456", "password": "newsecret1"},
    )
    assert r.status_code == 422

async def test_verified_user_passes_gate(client, gating_on, db_session):
    from sqlalchemy import update
    from app.core.models import User

    await client.post(
        "/api/auth/register", json={"email": "g4@x.io", "password": "secret123"}
    )
    await client.post(
        "/api/auth/login", json={"email": "g4@x.io", "password": "secret123"}
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

async def test_gating_per_class_endpoints(client, gating_on):
    """P2: mọi class API đều gated 403 cho user chưa verify — exports,
    region_edit, admin, presign. /api/healthz không còn exempt (entry chết:
    route thật /healthz không prefix → bypass tự nhiên)."""
    await client.post(
        "/api/auth/register", json={"email": "g6@x.io", "password": "secret123"}
    )
    await client.post(
        "/api/auth/login", json={"email": "g6@x.io", "password": "secret123"}
    )
    assert (
        await client.post("/api/jobs/1/export", json={"fmt": "md"})
    ).status_code == 403
    assert (
        await client.patch("/api/jobs/1/regions/1", json={})
    ).status_code == 403
    assert (await client.get("/api/admin/users")).status_code == 403
    assert (await client.post("/api/jobs/presign", json={})).status_code == 403
    assert (await client.get("/api/healthz")).status_code == 403

async def test_logout_and_refresh_exempt_for_unverified(client, gating_on):
    """P1-2: user chưa verify phải logout/refresh được để resend code."""
    await client.post(
        "/api/auth/register", json={"email": "g7@x.io", "password": "secret123"}
    )
    r = await client.post(
        "/api/auth/login", json={"email": "g7@x.io", "password": "secret123"}
    )
    assert r.status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 200
    assert (await client.post("/api/auth/logout")).status_code == 200

async def test_exempt_match_strips_trailing_slash(client, gating_on):
    """P2: exempt match strip trailing slash — /api/auth/login/ không dính
    403 gating (vẫn 401 từ route)."""
    r = await client.post(
        "/api/auth/login/", json={"email": "g8@x.io", "password": "secret123"}
    )
    # gate exempt (strip slash) → Starlette redirect 307 tới path chuẩn,
    # KHÔNG phải 403 email_unverified
    assert r.status_code in (307, 401)

async def test_gating_off_in_test_env(client):
    """env=test (conftest) → middleware skip: register xong xài được ngay."""
    await client.post(
        "/api/auth/register", json={"email": "g5@x.io", "password": "secret123"}
    )
    await client.post(
        "/api/auth/login", json={"email": "g5@x.io", "password": "secret123"}
    )
    assert (await client.get("/api/auth/me")).status_code == 200
