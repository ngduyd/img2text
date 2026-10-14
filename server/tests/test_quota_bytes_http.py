"""Wave-5 S1 HTTP: create ghi upload_bytes thật, gate 429 upload_quota,
refund khi cancelled/failed, serializer + list fields.

Ruling: reject 429 không auto-evict; gate bytes SAU 422 validation.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.models import Job, User
from tests.conftest import TEST_JPEG, TEST_PDF_3, upload_job


async def _latest_user(db_session) -> User:
    return (
        await db_session.scalars(select(User).order_by(User.id.desc()).limit(1))
    ).one()

async def test_create_job_records_real_bytes(auth_client, app, db_session):
    r = await upload_job(auth_client, app.state.storage, TEST_JPEG, "a.jpg")
    assert r.status_code == 201, r.text
    job = await db_session.get(Job, r.json()["id"])
    assert job.upload_bytes == len(TEST_JPEG)
    assert job.storage_purged_at is None

async def test_create_over_bytes_429_structured(auth_client, app, db_session):
    """Used 600B + upload 300B > limit 800B → 429 {code,used,limit,oldest}."""
    user = await _latest_user(db_session)
    user.upload_byte_limit = 800
    await db_session.commit()
    db_session.add(Job(
        user_id=user.id, status="done", storage_key="uploads/old.bin",
        file_type="image", page_count=1, upload_bytes=600,
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    await db_session.commit()
    r = await upload_job(auth_client, app.state.storage, TEST_PDF_3, "a.pdf")  # ~3 trang PDF > 200B
    assert r.status_code == 429, r.text
    d = r.json()["detail"]
    assert d["code"] == "upload_quota" and d["used_bytes"] == 600
    assert d["limit_bytes"] == 800
    assert d["oldest_expires_at"]  # thời điểm bytes trôi khỏi cửa sổ

async def test_cancel_refunds_bytes(auth_client, app, db_session):
    r = await upload_job(auth_client, app.state.storage, TEST_JPEG, "a.jpg")
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    assert (await auth_client.post(f"/api/jobs/{jid}/cancel")).status_code == 204
    job = await db_session.get(Job, jid)
    assert job.upload_bytes == 0  # refund

# --- review P1: refund transitions còn thiếu test ---------------------------

async def test_fail_endpoint_refunds_bytes(worker_client, seed_job, db_session):
    """POST /fail (extracting claim) → upload_bytes=0 (refund)."""
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    assert job.upload_bytes > 0  # create đã ghi bytes thật
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/fail", json={"error": "boom"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "failed" and job.upload_bytes == 0  # refund

async def test_render_fail_refunds_bytes(db_session, VALID_RESULT_JSONB, monkeypatch):
    """_auto_output cả 2 layout fail → failed/rendering + refund upload_bytes=0."""
    from app.services import job_results

    jid = await _rendering_job_with_bytes(db_session, VALID_RESULT_JSONB, nbytes=777)

    async def _gen(job, storage):
        return False  # cả 2 pass fail → completion rule: failed

    monkeypatch.setattr("app.routers.exports.auto_generate_output", _gen)
    job = await db_session.get(Job, jid)
    await job_results._auto_output(job, None)
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "failed" and job.failed_step == "rendering"
    assert job.upload_bytes == 0  # refund

async def _rendering_job_with_bytes(db_session, result, nbytes):
    """Job rendering + upload_bytes=N (refund transition pattern: seed N → trigger → assert 0)."""
    from sqlalchemy import select

    from app.core.models import Job, User

    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    if user is None:  # chưa có auth_client → seed user trực tiếp
        user = User(email="refund@test.io", password_hash="x", role="user")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    job = Job(
        user_id=user.id, status="rendering", result=result,
        storage_key="uploads/test.jpg", file_type="image", page_count=1,
        upload_bytes=nbytes,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

async def test_serializer_includes_purge_fields(auth_client, app, db_session):
    r = await upload_job(auth_client, app.state.storage, TEST_JPEG, "a.jpg")
    jid = r.json()["id"]
    detail = await auth_client.get(f"/api/jobs/{jid}")
    body = detail.json()
    assert body["upload_bytes"] == len(TEST_JPEG)
    assert body["storage_purged_at"] is None
    lst = (await auth_client.get("/api/jobs")).json()["items"][0]
    assert lst["upload_bytes"] == len(TEST_JPEG)
    assert "storage_purged_at" in lst
