"""#1 DELETE /api/jobs/{id} — owner/admin 204, storage+row gone, 403 khác."""

import hashlib
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.models import DocumentVersion, Job
from tests.conftest import TEST_JPEG, upload_job


@pytest_asyncio.fixture
async def other_client(app, db_session):
    """User khác (ocr granted) — cần cho 403 test."""
    from httpx import ASGITransport, AsyncClient

    from app.core.deps import ACCESS_COOKIE
    from tests.conftest import grant_ocr

    email = f"o-{uuid4().hex}@test.io"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
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
        yield c


async def _seed_done_job(upload, storage, db_session):
    """Upload thật + job done + derived export/crops/versions objects."""
    r = await upload(TEST_JPEG, "a.jpg", page_count=1)
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    input_key = f"uploads/{hashlib.sha256(TEST_JPEG).hexdigest()}.jpg"
    assert await storage.exists(input_key)
    await storage.put(f"exports/{job_id}/md", b"# out")
    await storage.put(f"crops/{job_id}/r0.jpg", b"\xff\xd8")
    await storage.put(f"versions/{job_id}/text/1", b"v1")
    job = await db_session.get(Job, job_id)
    job.status = "done"
    db_session.add(
        DocumentVersion(
            job_id=job_id, kind="text", storage_key=f"versions/{job_id}/text/1",
            version=1,
        )
    )
    await db_session.commit()
    return job_id, input_key


async def test_delete_owner_cleans_storage_and_row(
    auth_client, upload, storage_spy, db_session
):
    job_id, input_key = await _seed_done_job(upload, storage_spy, db_session)
    r = await auth_client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 204, r.text
    # storage gone (mock driver assert + real state)
    called = [c.args[0] for c in storage_spy.delete_prefix.call_args_list]
    assert f"exports/{job_id}/" in called
    assert f"crops/{job_id}/" in called
    assert f"versions/{job_id}/" in called
    assert input_key in called  # input object (job.storage_key)
    for key in (
        f"exports/{job_id}/md",
        f"crops/{job_id}/r0.jpg",
        f"versions/{job_id}/text/1",
        input_key,
    ):
        assert await storage_spy.exists(key) is False
    # row gone: GET → 404, versions rows cascade
    assert (await auth_client.get(f"/api/jobs/{job_id}")).status_code == 404
    db_session.expire_all()
    assert await db_session.get(Job, job_id) is None
    leftover = (
        await db_session.execute(
            select(DocumentVersion).where(DocumentVersion.job_id == job_id)
        )
    ).scalars().all()
    assert leftover == []


async def test_delete_other_user_403(auth_client, other_client, upload, storage, db_session):
    job_id, _ = await _seed_done_job(upload, storage, db_session)
    assert (await other_client.delete(f"/api/jobs/{job_id}")).status_code == 403
    assert (await auth_client.delete(f"/api/jobs/{job_id}")).status_code == 204


async def test_delete_extracting_allowed(
    auth_client, worker_client, upload, storage, db_session
):
    """Đang extracting → vẫn xóa được (ingest/worker guard job-missing)."""
    r = await upload(TEST_JPEG, "b.jpg", page_count=1)
    job_id = r.json()["id"]
    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200
    assert (await auth_client.delete(f"/api/jobs/{job_id}")).status_code == 204
    # worker path sau khi job biến mất → 404 (không 500)
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{job_id}/result",
        json={
            "model_version": "m", "gpu_seconds": 1.0, "warnings": [],
            "markdown": "x",
            "pages": [{"index": 0, "width": 1, "height": 1, "page_flag": "ok",
                       "markdown": "x", "regions": []}],
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 404

# --- review r1 P1-1: input object content-addressed dùng chung (refcount) ----

async def test_delete_keeps_shared_input_until_last_job(
    auth_client, upload, storage_spy, db_session
):
    """2 job cùng sha → cùng storage_key; xóa A không được đụng input khi B sống."""
    a = (await upload(TEST_JPEG, "a.jpg", page_count=1)).json()["id"]
    b = (await upload(TEST_JPEG, "b.jpg", page_count=1)).json()["id"]
    key_a = (await db_session.get(Job, a)).storage_key
    db_session.expire_all()
    key_b = (await db_session.get(Job, b)).storage_key
    assert key_a == key_b  # content-addressed dedupe
    assert (await auth_client.delete(f"/api/jobs/{a}")).status_code == 204
    assert await storage_spy.exists(key_a) is True  # job B vẫn sống → input giữ
    assert (await auth_client.delete(f"/api/jobs/{b}")).status_code == 204
    assert await storage_spy.exists(key_a) is False  # job cuối → input xóa

# --- review r1 P2: DELETE nulls worker_heartbeats.current_job_id -------------

async def test_delete_nulls_worker_heartbeat_current_job(
    auth_client, upload, db_session
):
    from datetime import datetime, timezone

    from app.core.models import WorkerHeartbeat

    job_id = (await upload(TEST_JPEG, "hb.jpg", page_count=1)).json()["id"]
    db_session.add(
        WorkerHeartbeat(
            worker_id="w-del", kind="loop",
            last_seen=datetime.now(timezone.utc), current_job_id=job_id,
        )
    )
    await db_session.commit()
    assert (await auth_client.delete(f"/api/jobs/{job_id}")).status_code == 204
    db_session.expire_all()
    row = await db_session.get(WorkerHeartbeat, "w-del")
    assert row is not None  # heartbeat row không crash, giữ
    assert row.current_job_id is None  # job gone → không trỏ mồ côi
