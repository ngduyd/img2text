"""Task 3: GET /api/jobs, GET /api/jobs/{id}, GET /api/jobs/{id}/file."""

from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Job, User


@pytest_asyncio.fixture
async def other_client(app, db_session):
    """Second registered+logged-in user; own httpx client (own cookies)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        email = f"other-{uuid4().hex}@test.io"
        r = await c.post(
            "/api/auth/register", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 201, r.text
        r = await c.post(
            "/api/auth/login", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 200, r.text
        yield c


async def _user_id(session: AsyncSession, email_prefix: str) -> int:
    return (
        await session.execute(
            select(User.id).where(User.email.like(f"{email_prefix}%"))
        )
    ).scalar_one()


async def _seed(session: AsyncSession, user_id: int, storage_key: str) -> int:
    job = Job(
        user_id=user_id,
        storage_key=storage_key,
        file_type="image",
        page_count=1,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id


@pytest_asyncio.fixture
async def seed_job(db_session, auth_client) -> int:
    """One queued job owned by the auth_client user."""
    return await _seed(db_session, await _user_id(db_session, "u-"), "uploads/abc.jpg")


@pytest_asyncio.fixture
async def seed_two_jobs(db_session, auth_client, other_client) -> dict:
    """Two jobs each: auth user and other user."""
    mine = [
        await _seed(db_session, await _user_id(db_session, "u-"), "uploads/a.jpg"),
        await _seed(db_session, await _user_id(db_session, "u-"), "uploads/b.jpg"),
    ]
    await _seed(db_session, await _user_id(db_session, "other-"), "uploads/c.jpg")
    return {"mine": mine}


async def test_list_only_mine(auth_client, other_client, seed_two_jobs):
    r = await auth_client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(seed_two_jobs["mine"])
    assert all(j["id"] in seed_two_jobs["mine"] for j in body["items"])


# --- Phase 4 (plan Task 1): server-side pagination ---

@pytest_asyncio.fixture
async def seed_twelve_jobs(db_session, auth_client) -> list[int]:
    """12 queued jobs for the auth user (default page holds 10)."""
    uid = await _user_id(db_session, "u-")
    return [await _seed(db_session, uid, f"uploads/p{i}.jpg") for i in range(12)]

async def test_list_default_pagination(auth_client, seed_twelve_jobs):
    r = await auth_client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] == 12
    assert len(body["items"]) == 10

async def test_list_page_two_partitions(auth_client, seed_twelve_jobs):
    b1 = (await auth_client.get("/api/jobs")).json()
    b2 = (await auth_client.get("/api/jobs?page=2")).json()
    assert b2["page"] == 2 and b2["total"] == 12 and len(b2["items"]) == 2
    ids1 = {j["id"] for j in b1["items"]}
    ids2 = {j["id"] for j in b2["items"]}
    assert not ids1 & ids2  # pages never overlap
    assert ids1 | ids2 == set(seed_twelve_jobs)  # pages cover every job

async def test_list_page_size_bounds(auth_client, seed_twelve_jobs):
    r = await auth_client.get("/api/jobs?page_size=100")
    assert r.status_code == 200 and r.json()["page_size"] == 100
    assert len(r.json()["items"]) == 12
    assert (await auth_client.get("/api/jobs?page_size=101")).status_code == 422
    assert (await auth_client.get("/api/jobs?page=0")).status_code == 422

async def test_list_empty_page_beyond_range(auth_client, seed_twelve_jobs):
    body = (await auth_client.get("/api/jobs?page=3")).json()
    assert body["items"] == [] and body["total"] == 12 and body["page"] == 3

async def test_detail_owner_ok(auth_client, seed_job):
    r = await auth_client.get(f"/api/jobs/{seed_job}")
    assert r.status_code == 200 and r.json()["status"] == "queued"


async def test_detail_other_user_403(auth_client, other_client, seed_job):
    assert (await other_client.get(f"/api/jobs/{seed_job}")).status_code == 403

# --- P0-D: GET job → text_version + stale_layouts (web contract) ---

async def test_detail_stale_layouts_when_based_on_behind(
    auth_client, app, seed_job, db_session
):
    """Layout version row based_on_text_version < job.text_version → kind có mặt."""
    from app.services.doc_versions import save_version

    jid = seed_job
    await app.state.storage.put(f"exports/{jid}/md-layout", b"# x")
    await save_version(
        app.state.storage, jid, "md-layout", b"# x", 0, session=db_session
    )
    job = await db_session.get(Job, jid)
    job.text_version = 1  # text edit sau khi layout render
    await db_session.commit()
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["text_version"] == 1
    assert body["stale_layouts"] == ["md"]

async def test_detail_stale_layouts_empty_when_current_or_absent(
    auth_client, app, seed_job, db_session
):
    """Không có row → []; based_on == text_version → []."""
    from app.services.doc_versions import save_version

    jid = seed_job
    # không layout row → không tính stale
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["text_version"] == 0
    assert body["stale_layouts"] == []
    # row based_on == text_version → không stale
    await app.state.storage.put(f"exports/{jid}/md-layout", b"# x")
    await save_version(
        app.state.storage, jid, "md-layout", b"# x", 0, session=db_session
    )
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["stale_layouts"] == []


async def test_file_presign_owner(auth_client, seed_job):
    r = await auth_client.get(f"/api/jobs/{seed_job}/file")
    assert r.status_code == 200 and "uploads/" in r.json()["url"]

# --- P1-2 review r1: GET job trả mode — web ẩn Section Layout khi extract_only ---

async def test_detail_returns_mode(auth_client, seed_job, db_session):
    body = (await auth_client.get(f"/api/jobs/{seed_job}")).json()
    assert body["mode"] == "layout"  # default (legacy NULL row cũng phải là "layout")
    job = await db_session.get(Job, seed_job)
    job.mode = "extract_only"
    await db_session.commit()
    body = (await auth_client.get(f"/api/jobs/{seed_job}")).json()
    assert body["mode"] == "extract_only"

# --- wave-2 #3: q (ILIKE filename) + status (single) + sort newest|oldest ---

async def _seed_named(
    session: AsyncSession, user_id: int, filename: str, status: str, days_ago: int
) -> int:
    from datetime import datetime, timedelta, timezone

    job = Job(
        user_id=user_id, storage_key=f"uploads/{abs(hash(filename))}.pdf",
        file_type="pdf", page_count=1, filename=filename, status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.id

@pytest_asyncio.fixture
async def three_named_jobs(db_session, auth_client) -> dict:
    uid = await _user_id(db_session, "u-")
    oldest = await _seed_named(db_session, uid, "bao-cao-thang-1.pdf", "done", 3)
    failed = await _seed_named(db_session, uid, "bieu-mau-ku.pdf", "failed", 2)
    newest = await _seed_named(db_session, uid, "bao-cao-thang-2.pdf", "queued", 1)
    return {"oldest": oldest, "failed": failed, "newest": newest}

async def test_list_q_ilike_filename(auth_client, three_named_jobs):
    items = (await auth_client.get("/api/jobs", params={"q": "BAO"})).json()
    # ILIKE: hoa/thường không phân biệt; default newest trước
    assert [j["id"] for j in items["items"]] == [
        three_named_jobs["newest"], three_named_jobs["oldest"],
    ]
    assert items["total"] == 2

async def test_list_status_single_value(auth_client, three_named_jobs):
    items = (await auth_client.get("/api/jobs", params={"status": "failed"})).json()
    assert [j["id"] for j in items["items"]] == [three_named_jobs["failed"]]
    assert items["total"] == 1

async def test_list_sort_oldest(auth_client, three_named_jobs):
    items = (await auth_client.get("/api/jobs", params={"sort": "oldest"})).json()
    assert items["items"][0]["id"] == three_named_jobs["oldest"]
    # default giữ newest
    default = (await auth_client.get("/api/jobs")).json()
    assert default["items"][0]["id"] == three_named_jobs["newest"]

async def test_list_sort_invalid_422(auth_client):
    assert (
        await auth_client.get("/api/jobs", params={"sort": "random"})
    ).status_code == 422

async def test_create_stores_filename(upload, db_session):
    """upload helper gửi filename (web lane cũng gửi) → cột filename."""
    from tests.conftest import TEST_PDF_3

    r = await upload(TEST_PDF_3, "ho-so.pdf", page_count=1)
    assert r.status_code == 201, r.text
    job = await db_session.get(Job, r.json()["id"])
    assert job.filename == "ho-so.pdf"
