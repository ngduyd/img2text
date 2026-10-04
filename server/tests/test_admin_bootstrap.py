"""Task 8: admin bootstrap + temporary /api/admin/__probe route."""

from sqlalchemy import select

from app.admin import bootstrap_admin
from app.models import User


async def test_bootstrap_admin_creates_admin_and_is_idempotent(db_session):
    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    u = (
        await db_session.execute(select(User).where(User.email == "admin@x.io"))
    ).scalar_one()
    assert u.role == "admin"

    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    rows = (
        await db_session.execute(select(User).where(User.email == "admin@x.io"))
    ).scalars().all()
    assert len(rows) == 1


async def test_bootstrap_admin_noop_on_empty_email(db_session):
    await bootstrap_admin(db_session, "", "whatever")
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 0


async def test_admin_probe_403_for_registered_user(client):
    resp = await client.post(
        "/api/auth/register", json={"email": "n@x.io", "password": "secret123"}
    )
    assert resp.status_code == 201
    probe = await client.get("/api/admin/__probe")
    assert probe.status_code == 403


async def test_admin_probe_200_for_admin(client, db_session):
    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    login = await client.post(
        "/api/auth/login", json={"email": "admin@x.io", "password": "adminpass1"}
    )
    assert login.status_code == 200
    probe = await client.get("/api/admin/__probe")
    assert probe.status_code == 200
    assert probe.json() == {"ok": True}
