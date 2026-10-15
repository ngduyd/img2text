"""Lane ST (user storage page): POST /api/jobs/purge-storage-due — auth, KHÔNG
admin. Purge batch CỦA user (done + cũ hơn retention + auto_purge + chưa purge):
A purge không đụng jobs B, jobs chưa hết hạn giữ. + GET /api/jobs serializer
trả upload_bytes + storage_purged_at (verify Lane M1)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select

from app.core.deps import ACCESS_COOKIE
from app.core.models import Job, User
from tests.conftest import grant_ocr


async def _register_login(app, db_session, prefix: str):
    """User mới (ocr granted) → (client riêng, user_id)."""
    email = f"{prefix}-{uuid4().hex}@test.io"
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    r = await c.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201, r.text
    await grant_ocr(db_session, email)
    r = await c.post(
        "/api/auth/login", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 200, r.text
    assert ACCESS_COOKIE in c.cookies
    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    return c, user.id


@pytest_asyncio.fixture
async def user_a(app, db_session):
    c, uid = await _register_login(app, db_session, "a")
    yield c, uid
    await c.aclose()


@pytest_asyncio.fixture
async def user_b(app, db_session):
    c, uid = await _register_login(app, db_session, "b")
    yield c, uid
    await c.aclose()


async def _done_job(db_session, user_id, *, age_days: int, key: str, **kw) -> Job:
    job = Job(
        user_id=user_id, status="done", storage_key=key, file_type="pdf",
        page_count=1,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        **kw,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


async def test_purge_storage_due_isolates_users_and_retention(
    user_a, user_b, db_session, storage
):
    ca, ida = user_a
    cb, idb = user_b
    a_old = await _done_job(db_session, ida, age_days=10, key="uploads/a-old.pdf", upload_bytes=111)
    a_fresh = await _done_job(db_session, ida, age_days=1, key="uploads/a-new.pdf")
    b_old = await _done_job(db_session, idb, age_days=10, key="uploads/b-old.pdf")
    for key, blob in (
        ("uploads/a-old.pdf", b"%PDF a-old"),
        ("uploads/a-new.pdf", b"%PDF a-new"),
        ("uploads/b-old.pdf", b"%PDF b-old"),
    ):
        await storage.put(key, blob)

    r = await ca.post("/api/jobs/purge-storage-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"purged": 1}
    # A: job cũ purge, job mới giữ
    assert not await storage.exists("uploads/a-old.pdf")
    assert await storage.exists("uploads/a-new.pdf")
    # B: A không đụng jobs B
    assert await storage.exists("uploads/b-old.pdf")
    for job, purged in ((a_old, True), (a_fresh, False), (b_old, False)):
        await db_session.refresh(job)
        assert (job.storage_purged_at is not None) is purged, job.id

    # B tự purge → chỉ jobs B
    r = await cb.post("/api/jobs/purge-storage-due")
    assert r.status_code == 200 and r.json() == {"purged": 1}, r.text
    assert not await storage.exists("uploads/b-old.pdf")
    assert await storage.exists("uploads/a-new.pdf")


async def test_purge_storage_due_requires_auth(client):
    r = await client.post("/api/jobs/purge-storage-due")
    assert r.status_code == 401


async def test_list_jobs_exposes_upload_bytes_and_purged_flag(
    user_a, db_session
):
    ca, uid = user_a
    kept = await _done_job(db_session, uid, age_days=2, key="uploads/k.pdf", upload_bytes=1234)
    gone = await _done_job(
        db_session, uid, age_days=9, key="uploads/g.pdf", upload_bytes=4321,
        storage_purged_at=datetime.now(timezone.utc),
    )
    r = await ca.get("/api/jobs")
    assert r.status_code == 200, r.text
    by_id = {j["id"]: j for j in r.json()["items"]}
    assert by_id[kept.id]["upload_bytes"] == 1234
    assert by_id[kept.id]["storage_purged_at"] is None
    assert by_id[gone.id]["upload_bytes"] == 4321
    assert by_id[gone.id]["storage_purged_at"] is not None
