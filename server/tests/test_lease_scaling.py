"""Spec 2026-11-04 (T1): lease sống theo trang + poll status gia hạn + cap
lần reap.

B2  → lease claim = min(base + per_page × page_count, cap) phút.
B1″ → GET /api/jobs/{id}/status (session, extracting) gia hạn lease lên
      now + job_page_lease_minutes (worker chết = ngừng poll).
B3  → reap_leases đếm attempts; chạm job_max_attempts → failed + error.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, User, WorkerSession
from app.core.security import hash_worker_token
from app.services.jobs_requeue import reap_leases

SESSION_KEY = "ws-lease-key-0001"
OTHER_KEY = "ws-lease-key-0002"

async def _seed_session(db_session, key: str = SESSION_KEY) -> int:
    row = WorkerSession(
        kernel_ref="testuser/img2text-session",
        key_hash=hash_worker_token(key),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row.id

async def _seed_queued_job(db_session, page_count: int = 1) -> int:
    user_row = (
        await db_session.execute(select(User).order_by(User.id).limit(1))
    ).scalars().first()
    if user_row is None:
        user_row = User(email="ws-lease@x.io", password_hash="x")
        db_session.add(user_row)
        await db_session.commit()
    job = Job(
        user_id=user_row.id,
        status="queued",
        storage_key="uploads/ws-lease.jpg",
        file_type="image",
        page_count=page_count,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

def _auth(key: str = SESSION_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}

async def _claim_session(client, db_session, page_count: int = 1) -> Job:
    jid = await _seed_queued_job(db_session, page_count)
    r = await client.get("/api/jobs/next", headers=_auth())
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == jid
    job = await db_session.get(Job, jid)
    assert job.status == "extracting"
    return job

async def test_lease_scales_1_page_24_minutes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    job = await _claim_session(client, db_session, page_count=1)
    assert job.lease_expires_at - job.started_at == timedelta(minutes=24)

async def test_lease_scales_9_pages_56_minutes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    job = await _claim_session(client, db_session, page_count=9)
    assert job.lease_expires_at - job.started_at == timedelta(minutes=56)

async def test_lease_scales_40_pages_hits_cap_90_minutes(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    job = await _claim_session(client, db_session, page_count=40)
    assert job.lease_expires_at - job.started_at == timedelta(minutes=90)

async def test_lease_loop_claim_uses_same_formula(
    worker_client, db_session, monkeypatch
):
    """Claim loop mode (runner key) dùng CHUNG công thức với session claim."""
    monkeypatch.setattr(settings, "kaggle_mode", "loop")
    jid = await _seed_queued_job(db_session, page_count=9)
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200, r.text
    job = await db_session.get(Job, jid)
    assert job.lease_expires_at - job.started_at == timedelta(minutes=56)

async def test_status_poll_extends_lease_to_10_minutes(
    client, db_session, monkeypatch
):
    """B1″ AC5: lease gần hết → poll status gia hạn lên now+10′."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    job = await _claim_session(client, db_session, page_count=1)
    # giả lập lease gần cạn (worker đã chạy 23/24 phút)
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    await db_session.commit()
    polled_at = datetime.now(timezone.utc)
    r = await client.get(f"/api/jobs/{job.id}/status", headers=_auth())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "extracting"
    await db_session.refresh(job)
    lease_left = job.lease_expires_at - polled_at
    assert timedelta(minutes=9, seconds=30) < lease_left

async def test_status_poll_other_session_401_lease_unchanged(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    await _seed_session(db_session, OTHER_KEY)
    job = await _claim_session(client, db_session, page_count=1)
    before = job.lease_expires_at
    r = await client.get(
        f"/api/jobs/{job.id}/status", headers=_auth(OTHER_KEY)
    )
    assert r.status_code == 401
    await db_session.refresh(job)
    assert job.lease_expires_at == before

async def test_attempts_cap_marks_job_failed_after_3_reaps(
    client, db_session, monkeypatch
):
    """B3 AC6: reap lần 1-2 → queued (attempts 1,2); lần 3 → failed + error."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    job = await _claim_session(client, db_session, page_count=1)
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)

    for expected in (1, 2):
        job.lease_expires_at = expired
        await db_session.commit()
        assert await reap_leases(db_session) == 1
        await db_session.refresh(job)
        assert job.status == "queued"
        assert job.attempts == expected
        assert job.error is None
        # claim lại để lần reap kế tiếp thấy extracting
        r = await client.get("/api/jobs/next", headers=_auth())
        assert r.status_code == 200, r.text
        assert r.json()["job_id"] == job.id
        await db_session.refresh(job)
        assert job.status == "extracting"

    job.lease_expires_at = expired
    await db_session.commit()
    assert await reap_leases(db_session) == 1
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 3
    assert job.error is not None
    assert "không phản hồi" in job.error
    assert job.lease_expires_at is None
    # failed không còn reclaimable
    r = await client.get("/api/jobs/next", headers=_auth())
    assert r.status_code == 200 and r.json() == {"empty": True}
