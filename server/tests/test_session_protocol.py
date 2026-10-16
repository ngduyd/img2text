"""Spec kaggle session worker T4: session claim + protocol.

AC4: claim 200 JSON (session_key echo, result/crop presign PUT URLs);
AC4a: gpu_seconds writer → worker_sessions.gpu_seconds_reported;
AC7: cancel giữa các trang qua GET /status; AC8: done replay → 200 no-op.
Claim auth = Bearer session key (AC3 "Bearer mọi request") — server không
giữ plaintext nên claim echo key caller; hash-at-rest trong DB.
"""

import hashlib
from copy import deepcopy

from sqlalchemy import select, text

from app.core.config import settings
from app.core.models import Job, User, WorkerSession
from app.core.security import hash_worker_token
from tests.conftest import PNG_1PX

SESSION_KEY = "ws-protocol-key-0001"

async def _seed_session(db_session, key: str = SESSION_KEY) -> int:
    row = WorkerSession(
        kernel_ref="testuser/img2text-session",
        key_hash=hash_worker_token(key),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row.id

async def _seed_queued_job(db_session) -> int:
    user = (
        await db_session.execute(select(User).order_by(User.id).limit(1))
    ).scalars().first()
    if user is None:
        user = User(email="ws-proto@x.io", password_hash="x")
        db_session.add(user)
        await db_session.commit()
    job = Job(
        user_id=user.id,
        status="queued",
        storage_key="uploads/ws-proto.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

def _auth(key: str = SESSION_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}

async def test_claim_returns_200_session_key_and_upload_urls(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    sid = await _seed_session(db_session)
    jid = await _seed_queued_job(db_session)
    r = await client.get(
        "/api/jobs/next?crop_rids=r0,r1", headers=_auth()
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["job_id"] == jid
    assert b["session_key"] == SESSION_KEY
    assert b["session_id"] == sid
    assert f"jobs/{jid}/_result.json" in b["result_upload_url"]
    assert set(b["crop_upload_urls"]) == {"r0", "r1"}
    assert f"jobs/{jid}/crops/r0.png" in b["crop_upload_urls"]["r0"]
    assert b["server_flags"] == {"quota_low": False}
    # hash-at-rest: plaintext KHÔNG nằm trong row; key_hash == sha256
    row_text = await db_session.scalar(
        text("SELECT t::text FROM worker_sessions t WHERE id = :i"),
        {"i": sid},
    )
    assert SESSION_KEY not in row_text
    stored_hash = await db_session.scalar(
        text("SELECT key_hash FROM worker_sessions WHERE id = :i"), {"i": sid}
    )
    assert stored_hash == hashlib.sha256(SESSION_KEY.encode()).hexdigest()
    # session-scope claim: worker_token_hash giữ NULL (batch rider guards)
    job = await db_session.get(Job, jid)
    assert job.status == "extracting"
    assert job.worker_token_hash is None
    assert job.session_id == sid
    assert job.lease_expires_at is not None  # lease = kaggle_timeout (9h)

async def test_empty_queue_returns_200_empty_flag(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    r = await client.get("/api/jobs/next", headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"empty": True}

async def test_claim_with_closed_session_key_401(client, db_session, monkeypatch):
    """Session đóng (closed_at set) → claim 401 anti-oracle — không echo
    key, không claim; job queued giữ nguyên."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session, "closed-session-key")
    await db_session.execute(
        text("UPDATE worker_sessions SET closed_at = now()")
    )
    await db_session.commit()
    jid = await _seed_queued_job(db_session)
    r = await client.get("/api/jobs/next", headers=_auth("closed-session-key"))
    assert r.status_code == 401
    assert r.json()["detail"] == "bad session key"
    job = await db_session.get(Job, jid)
    assert job.status == "queued"  # không claim được

async def test_done_upload_then_result_writes_gpu_seconds(
    client, db_session, storage, VALID_RESULT_JSONB, monkeypatch
):
    monkeypatch.setattr(settings, "kaggle_mode", "session")

    async def _md_ok(*args, **kwargs):
        return "# layout md"

    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    sid = await _seed_session(db_session)
    jid = await _seed_queued_job(db_session)
    claim = await client.get("/api/jobs/next", headers=_auth())
    assert claim.status_code == 200, claim.text
    url = claim.json()["result_upload_url"]
    key = url.split("/", 3)[-1]  # presign path == storage key
    await storage.put(key, b'{"stub": true}')  # == worker PUT lên R2 (moto)
    body = deepcopy(VALID_RESULT_JSONB)
    body["gpu_seconds"] = 42.5
    r = await client.post(
        f"/api/jobs/{jid}/result", json=body, headers=_auth()
    )
    assert r.status_code == 200, r.text
    from app.services.job_results import drain_auto_output

    await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "done"
    assert job.result["model_version"] == body["model_version"]
    # AC4a: gpu_seconds writer
    ws = await db_session.get(WorkerSession, sid)
    assert ws.gpu_seconds_reported == 42.5

async def test_done_idempotent_replay(
    client, db_session, storage, VALID_RESULT_JSONB, monkeypatch
):
    """AC8: POST /result lần 2 cùng body → 200 no-op, result không đổi."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")

    async def _md_ok(*args, **kwargs):
        return "# layout md"

    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    await _seed_session(db_session)
    jid = await _seed_queued_job(db_session)
    await client.get("/api/jobs/next", headers=_auth())
    body = deepcopy(VALID_RESULT_JSONB)
    r1 = await client.post(f"/api/jobs/{jid}/result", json=body, headers=_auth())
    assert r1.status_code == 200, r1.text
    # drain TRƯỚC replay — fire-and-forget task không được rò sang test sau
    from app.services.job_results import drain_auto_output

    await drain_auto_output()
    db_session.expire_all()
    first_result = (await db_session.get(Job, jid)).result
    r2 = await client.post(f"/api/jobs/{jid}/result", json=body, headers=_auth())
    assert r2.status_code == 200, r2.text
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.result == first_result

async def test_fail_writes_gpu_seconds(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    sid = await _seed_session(db_session)
    jid = await _seed_queued_job(db_session)
    await client.get("/api/jobs/next", headers=_auth())
    r = await client.post(
        f"/api/jobs/{jid}/fail",
        json={"error": "OCR fail", "gpu_seconds": 7.0},
        headers=_auth(),
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "failed" and job.error == "OCR fail"
    ws = await db_session.get(WorkerSession, sid)
    assert ws.gpu_seconds_reported == 7.0

async def test_fail_idempotent_replay(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    jid = await _seed_queued_job(db_session)
    await client.get("/api/jobs/next", headers=_auth())
    body = {"error": "OCR fail", "gpu_seconds": 1.0}
    assert (await client.post(f"/api/jobs/{jid}/fail", json=body, headers=_auth())).status_code == 200
    r2 = await client.post(f"/api/jobs/{jid}/fail", json=body, headers=_auth())
    assert r2.status_code == 200

async def test_cancel_between_pages_via_status(
    auth_client, client, upload, db_session, monkeypatch
):
    """AC7: owner cancel → worker GET /status (session key) → cancelled."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    r = await upload(PNG_1PX, "t.png")
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    claim = await client.get("/api/jobs/next", headers=_auth())
    assert claim.json()["job_id"] == jid
    r = await auth_client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 204, r.text
    r = await client.get(f"/api/jobs/{jid}/status", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "cancelled"

async def test_status_route_rejects_other_session(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    sid_a = await _seed_session(db_session, "session-key-A")
    jid = await _seed_queued_job(db_session)
    claim = await client.get("/api/jobs/next", headers=_auth("session-key-A"))
    assert claim.json()["session_id"] == sid_a
    await _seed_session(db_session, "session-key-B")  # id lớn hơn
    r = await client.get(f"/api/jobs/{jid}/status", headers=_auth("session-key-B"))
    assert r.status_code == 401
    assert r.json()["detail"] == "bad session key"
    r = await client.get(f"/api/jobs/{jid}/status", headers=_auth("session-key-A"))
    assert r.status_code == 200

async def test_result_rejects_other_session(client, db_session, VALID_RESULT_JSONB, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    sid_a = await _seed_session(db_session, "session-key-A2")
    jid = await _seed_queued_job(db_session)
    claim = await client.get("/api/jobs/next", headers=_auth("session-key-A2"))
    assert claim.json()["session_id"] == sid_a
    await _seed_session(db_session, "session-key-B2")
    r = await client.post(
        f"/api/jobs/{jid}/result", json=VALID_RESULT_JSONB,
        headers=_auth("session-key-B2"),
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "bad session key"

async def test_heartbeat_accepts_session_key(client, db_session, monkeypatch):
    """T7 kernel heartbeat: /api/worker/heartbeat Bearer session key → 200."""
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    await _seed_session(db_session)
    r = await client.post(
        "/api/worker/heartbeat",
        json={"worker_id": "kaggle-session", "kind": "kaggle-session"},
        headers=_auth(),
    )
    assert r.status_code == 200, r.text
