"""Wave-5 S1 HTTP: POST /purge-storage opt-in + guard 410 purged trên retry.

GIỮ layout/crops/versions/row; done-only 409; idempotent 204; owner-or-admin.
"""

from app.core.models import Job, User
from tests.conftest import TEST_JPEG, upload_job


async def _done_job_with_upload(auth_client, app, db_session) -> int:
    """Upload thật → fake done (worker protocol bẻ trạng thái quá nặng)."""
    r = await upload_job(auth_client, app.state.storage, TEST_JPEG, "a.jpg")
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    job = await db_session.get(Job, jid)
    job.status = "done"
    await db_session.commit()
    await app.state.storage.put(f"exports/{jid}/pdf", b"%PDF out")
    await app.state.storage.put(f"exports/{jid}/docx", b"PK docx")
    await app.state.storage.put(f"exports/{jid}/md-layout", b"# keep")
    await app.state.storage.put(f"exports/{jid}/docx.html", b"<html/>")
    await app.state.storage.put(f"crops/{jid}/r0.jpg", b"crop")
    return jid

async def test_manual_purge_opt_in_deletes_keeps_layout(auth_client, app, db_session):
    jid = await _done_job_with_upload(auth_client, app, db_session)
    storage = app.state.storage
    key = (await db_session.get(Job, jid)).storage_key
    r = await auth_client.post(f"/api/jobs/{jid}/purge-storage")
    assert r.status_code == 204, r.text
    assert not await storage.exists(key)
    assert not await storage.exists(f"exports/{jid}/pdf")
    assert not await storage.exists(f"exports/{jid}/docx")
    assert await storage.exists(f"exports/{jid}/md-layout")
    assert await storage.exists(f"exports/{jid}/docx.html")
    assert await storage.exists(f"crops/{jid}/r0.jpg")
    await db_session.refresh(await db_session.get(Job, jid))
    job = await db_session.get(Job, jid)
    assert job.storage_purged_at is not None
    # idempotent
    assert (await auth_client.post(f"/api/jobs/{jid}/purge-storage")).status_code == 204

async def test_purge_not_done_409(auth_client, seed_job):
    r = await auth_client.post(f"/api/jobs/{seed_job}/purge-storage")
    assert r.status_code == 409

async def test_purge_foreign_403(auth_client, client, db_session, app):
    jid = await _done_job_with_upload(auth_client, app, db_session)
    # user khác login
    r = await client.post(
        "/api/auth/register", json={"email": "other@test.io", "password": "secret123"}
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/auth/login", json={"email": "other@test.io", "password": "secret123"}
    )
    assert r.status_code == 200
    assert (await client.post(f"/api/jobs/{jid}/purge-storage")).status_code == 403

async def test_retry_after_purge_410(auth_client, app, db_session):
    jid = await _done_job_with_upload(auth_client, app, db_session)
    # purge khi done (hợp lệ) → fail sau → retry bị guard
    assert (await auth_client.post(f"/api/jobs/{jid}/purge-storage")).status_code == 204
    job = await db_session.get(Job, jid)
    job.status = "failed"
    job.failed_step = "extracting"
    await db_session.commit()
    r = await auth_client.post(f"/api/jobs/{jid}/retry")
    assert r.status_code == 410
    assert r.json()["detail"] == {"code": "purged"}

async def test_detail_serializer_shows_purged(auth_client, app, db_session):
    jid = await _done_job_with_upload(auth_client, app, db_session)
    await auth_client.post(f"/api/jobs/{jid}/purge-storage")
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["storage_purged_at"] is not None
    lst = (await auth_client.get("/api/jobs")).json()["items"][0]
    assert lst["storage_purged_at"] is not None

# --- review P2a: /file + /file/download trả URL/stream tới object đã xóa ----

async def test_file_presign_after_purge_410(auth_client, app, db_session):
    """GET /file khi storage_purged_at set → 410 {code: purged} (không presign URL chết)."""
    jid = await _done_job_with_upload(auth_client, app, db_session)
    assert (await auth_client.post(f"/api/jobs/{jid}/purge-storage")).status_code == 204
    r = await auth_client.get(f"/api/jobs/{jid}/file")
    assert r.status_code == 410
    assert r.json()["detail"] == {"code": "purged"}

async def test_file_download_after_purge_410(auth_client, app, db_session):
    """GET /file/download khi storage_purged_at set → 410 {code: purged}."""
    jid = await _done_job_with_upload(auth_client, app, db_session)
    assert (await auth_client.post(f"/api/jobs/{jid}/purge-storage")).status_code == 204
    r = await auth_client.get(f"/api/jobs/{jid}/file/download")
    assert r.status_code == 410
    assert r.json()["detail"] == {"code": "purged"}
