"""Wave-5 S1: PATCH /api/auth/me — toggle auto_purge + dismiss purge_notice_seen.

Web settings page + first-upload notice (modal 1 lần) gọi endpoint này;
UserOut expose 2 field để web đọc state (spec: PUT /api/auth/me {auto_purge}
hoặc settings endpoint phù hợp — PATCH /me nhận cả 2 field optional).
"""

from sqlalchemy import select

from app.core.models import User


async def _latest_user(db_session) -> User:
    return (
        await db_session.scalars(select(User).order_by(User.id.desc()).limit(1))
    ).one()

async def test_me_exposes_purge_fields(auth_client):
    body = (await auth_client.get("/api/auth/me")).json()
    assert body["auto_purge"] is True
    assert body["purge_notice_seen"] is False

async def test_patch_me_toggle_auto_purge(auth_client, db_session):
    r = await auth_client.patch("/api/auth/me", json={"auto_purge": False})
    assert r.status_code == 200
    assert r.json()["auto_purge"] is False
    assert (await _latest_user(db_session)).auto_purge is False

async def test_patch_me_dismiss_notice(auth_client, db_session):
    r = await auth_client.patch("/api/auth/me", json={"purge_notice_seen": True})
    assert r.status_code == 200
    assert r.json()["purge_notice_seen"] is True
    assert (await _latest_user(db_session)).purge_notice_seen is True

async def test_patch_me_noop_keeps_values(auth_client, db_session):
    await auth_client.patch("/api/auth/me", json={"auto_purge": False})
    r = await auth_client.patch("/api/auth/me", json={"purge_notice_seen": True})
    assert r.json()["auto_purge"] is False  # field không gửi = giữ nguyên

async def test_patch_me_401_anon(client):
    r = await client.patch("/api/auth/me", json={"auto_purge": False})
    assert r.status_code == 401
