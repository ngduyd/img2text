"""Task 1: admin user list + PATCH ocr_enabled toggle."""

import pytest

from app.models import User


@pytest.fixture
async def seeded_users_5(db_session) -> int:
    """Seed 5 plain users directly in DB; returns count (total = 6 with admin)."""
    for i in range(5):
        db_session.add(
            User(email=f"seed-{i}@test.io", password_hash="x", role="user")
        )
    await db_session.commit()
    return 5


async def test_list_users(admin_client, seeded_users_5):
    r = await admin_client.get("/api/admin/users?page=1&size=2")
    assert r.status_code == 200 and len(r.json()["items"]) == 2 and r.json()["total"] == 6  # 5+admin


async def test_patch_ocr_enabled(admin_client, db_session, seeded_users_5):
    r = await admin_client.patch("/api/admin/users/2", json={"ocr_enabled": True})
    assert r.status_code == 200 and r.json()["ocr_enabled"] is True
    u = await db_session.get(User, 2)
    assert u.ocr_enabled is True


async def test_patch_422_non_bool(admin_client):
    r = await admin_client.patch("/api/admin/users/2", json={"ocr_enabled": "yes"})
    assert r.status_code == 422


async def test_patch_404_unknown(admin_client):
    assert (await admin_client.patch("/api/admin/users/9999", json={"ocr_enabled": True})).status_code == 404


async def test_admin_required_403(auth_client):
    assert (await auth_client.get("/api/admin/users")).status_code == 403
