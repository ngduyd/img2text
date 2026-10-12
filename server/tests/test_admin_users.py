"""Task 1: admin user list + PATCH ocr_enabled toggle + ocr-disable pin."""

from uuid import uuid4

import httpx
import pytest

from app.core.models import Job, User
from tests.conftest import PNG_1PX, grant_ocr, upload_job


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

async def test_patch_ocr_disable_keeps_queued_job_claimable(
    admin_client, db_session, app, worker_client
):
    """Pin (Plan E final review): PATCH ocr_enabled=false does NOT touch the
    job queue — require_ocr gates upload, NOT claim; job stays queued and
    claimable by the worker.

    Seeded on a separate httpx client: admin_client and auth_client share the
    same cookie jar, so a second login would clobber the admin session.
    """
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"pin-{uuid4().hex}@test.io"
    r = await c.post("/api/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201, r.text
    await grant_ocr(db_session, email)
    r = await c.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    r = await upload_job(c, app.state.storage, PNG_1PX, "t.png")
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    await c.aclose()

    job = await db_session.get(Job, job_id)
    r = await admin_client.patch(
        f"/api/admin/users/{job.user_id}", json={"ocr_enabled": False}
    )
    assert r.status_code == 200 and r.json()["ocr_enabled"] is False
    await db_session.refresh(job)
    assert job.status == "queued"  # require_ocr gates upload, NOT claim
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200 and r.json()["job_id"] == job_id

# --- WS-ADMIN T5: cột quota (đã dùng/còn) + inline edit 2 limit ---

async def test_list_users_quota_fields(admin_client, db_session, seeded_users_5):
    from app.services.quota import daily_window

    lo, _hi = daily_window()
    db_session.add(
        Job(
            user_id=2, status="done", storage_key="uploads/x.pdf",
            file_type="pdf", page_count=3, created_at=lo,
        )
    )
    await db_session.commit()
    r = await admin_client.get("/api/admin/users?page=1&size=10")
    assert r.status_code == 200
    items = {u["id"]: u for u in r.json()["items"]}
    assert items[2]["daily_limit"] == 25
    assert items[2]["daily_used"] == 3
    assert items[2]["daily_remaining"] == 22
    assert items[2]["weekly_used"] == 3
    assert items[1]["daily_used"] == 0  # không có job

async def test_patch_quota_inline(admin_client, db_session, seeded_users_5):
    r = await admin_client.patch(
        "/api/admin/users/2/quota",
        json={"daily_page_limit": 5, "weekly_page_limit": 50},
    )
    assert r.status_code == 204
    u = await db_session.get(User, 2)
    assert (u.daily_page_limit, u.weekly_page_limit) == (5, 50)

async def test_patch_quota_validation_422(admin_client, seeded_users_5):
    bad_bodies = [
        {"daily_page_limit": -1, "weekly_page_limit": 50},
        {"daily_page_limit": 5, "weekly_page_limit": 100001},
        {"daily_page_limit": "5", "weekly_page_limit": 50},
    ]
    for body in bad_bodies:
        r = await admin_client.patch("/api/admin/users/2/quota", json=body)
        assert r.status_code == 422, body

async def test_patch_quota_404_unknown(admin_client, seeded_users_5):
    r = await admin_client.patch(
        "/api/admin/users/9999/quota",
        json={"daily_page_limit": 5, "weekly_page_limit": 50},
    )
    assert r.status_code == 404
