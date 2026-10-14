"""Wave-5 S1: purge binary — GIỮ layout/crops/versions/row; batch filter;
dedupe content-addressed (2 job cùng key → object sống đến job cuối)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import Job, User
from app.services.purge import purge_binary, purge_due_jobs


@pytest.fixture
async def seeded_user(db_session) -> User:
    u = User(email="p@test.io", password_hash="x", role="user")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u

async def _done_job(db_session, user_id, *, key, age_days, status="done", **kw):
    job = Job(
        user_id=user_id, status=status, storage_key=key, file_type="pdf",
        page_count=1,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        **kw,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job

async def _seed_storage(storage, job_id, *, pdf=True, docx=True):
    await storage.put(f"uploads/h{job_id}.pdf", b"%PDF orig")
    if pdf:
        await storage.put(f"exports/{job_id}/pdf", b"%PDF out")
    if docx:
        await storage.put(f"exports/{job_id}/docx", b"PK docx")
    # GIỮ-đạt: layout + html + crops
    await storage.put(f"exports/{job_id}/md-layout", b"# layout")
    await storage.put(f"exports/{job_id}/docx.html", b"<html/>")
    await storage.put(f"exports/{job_id}/crops/r0.png", b"PNG")
    await storage.put(f"crops/{job_id}/r0.jpg", b"JPEG")

async def test_purge_binary_deletes_only_regen_keys(db_session, seeded_user, storage):
    job = await _done_job(db_session, seeded_user.id, key="uploads/h1.pdf", age_days=1)
    await _seed_storage(storage, job.id)
    await purge_binary(db_session, storage, job)
    await db_session.commit()
    assert not await storage.exists("uploads/h1.pdf")
    assert not await storage.exists(f"exports/{job.id}/pdf")
    assert not await storage.exists(f"exports/{job.id}/docx")
    # GIỮ theo spec
    assert await storage.exists(f"exports/{job.id}/md-layout")
    assert await storage.exists(f"exports/{job.id}/docx.html")
    assert await storage.exists(f"exports/{job.id}/crops/r0.png")
    assert await storage.exists(f"crops/{job.id}/r0.jpg")
    await db_session.refresh(job)
    assert job.storage_purged_at is not None  # job row giữ nguyên

async def test_shared_storage_key_kept_until_last_job(db_session, seeded_user, storage):
    j1 = await _done_job(db_session, seeded_user.id, key="uploads/same.pdf", age_days=9)
    j2 = await _done_job(db_session, seeded_user.id, key="uploads/same.pdf", age_days=1)
    await storage.put("uploads/same.pdf", b"%PDF shared")
    await purge_binary(db_session, storage, j1)
    await db_session.commit()
    assert await storage.exists("uploads/same.pdf")  # j2 còn trỏ → giữ
    await purge_binary(db_session, storage, j2)
    await db_session.commit()
    assert not await storage.exists("uploads/same.pdf")  # job cuối → xóa

async def test_purge_due_jobs_batch_filters(db_session, seeded_user, storage):
    old = await _done_job(db_session, seeded_user.id, key="uploads/o.pdf", age_days=8)
    fresh = await _done_job(db_session, seeded_user.id, key="uploads/f.pdf", age_days=1)
    await storage.put("uploads/o.pdf", b"a")
    await storage.put("uploads/f.pdf", b"b")
    n = await purge_due_jobs(db_session, storage, retention_days=7)
    assert n == 1
    await db_session.refresh(old)
    assert old.storage_purged_at is not None
    await db_session.refresh(fresh)
    assert fresh.storage_purged_at is None
    # idempotent: tick kế → không purge lại
    assert await purge_due_jobs(db_session, storage, retention_days=7) == 0

async def test_purge_due_jobs_respects_auto_purge_and_status(db_session, seeded_user, storage):
    off = await _done_job(db_session, seeded_user.id, key="uploads/off.pdf", age_days=8)
    seeded_user.auto_purge = False
    await db_session.commit()
    queued = await _done_job(
        db_session, seeded_user.id, key="uploads/q.pdf", age_days=8, status="queued"
    )  # noqa — fake row, không claim
    await storage.put("uploads/off.pdf", b"a")
    await storage.put("uploads/q.pdf", b"b")
    assert await purge_due_jobs(db_session, storage, retention_days=7) == 0
    await db_session.refresh(off)
    await db_session.refresh(queued)
    assert off.storage_purged_at is None and queued.storage_purged_at is None
