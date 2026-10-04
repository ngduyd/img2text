"""Task 1: admin user list + PATCH ocr_enabled toggle + ocr-disable pin."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models import Job, User
from tests.conftest import PNG_1PX, grant_ocr


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
    r = await c.post("/api/jobs", files={"file": ("t.png", PNG_1PX, "image/png")})
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
