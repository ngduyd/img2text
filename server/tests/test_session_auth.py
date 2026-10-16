"""Spec kaggle session worker T3: per-session Bearer auth (get_session_key).

Anti-oracle: mọi lỗi (thiếu header/sai scheme/key lạ/session đóng) → 401
cùng detail "bad session key". Rate-limit per-IP 60/phút (in-process,
single-worker assumption). Worker route kiểm thử = GET /api/jobs/{id}/status
(T4 protocol surface).
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.models import Job, User, WorkerSession
from app.core.security import hash_worker_token

BAD_DETAIL = "bad session key"
LIVE_KEY = "session-key-live-abc"
CLOSED_KEY = "session-key-closed-xyz"

async def _seed_session(db_session, key: str, *, closed: bool = False) -> int:
    row = WorkerSession(
        kernel_ref="testuser/img2text-session",
        key_hash=hash_worker_token(key),
        closed_at=datetime.now(timezone.utc) if closed else None,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row.id

async def _seed_claimed_job(db_session, session_id: int) -> int:
    user = (
        await db_session.execute(select(User).order_by(User.id).limit(1))
    ).scalars().first()
    if user is None:
        user = User(email="ws-session@x.io", password_hash="x")
        db_session.add(user)
        await db_session.commit()
    job = Job(
        user_id=user.id,
        status="extracting",
        storage_key="uploads/ws.jpg",
        file_type="image",
        page_count=1,
        session_id=session_id,
    )
    db_session.add(job)
    await db_session.commit()
    return job.id

async def test_session_key_accepts_live(client, db_session):
    sid = await _seed_session(db_session, LIVE_KEY)
    job_id = await _seed_claimed_job(db_session, sid)
    r = await client.get(
        f"/api/jobs/{job_id}/status",
        headers={"Authorization": f"Bearer {LIVE_KEY}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "extracting", "error": None}

async def test_session_key_rejects_unknown_and_closed(client, db_session):
    sid = await _seed_session(db_session, LIVE_KEY)
    _closed_sid = await _seed_session(db_session, CLOSED_KEY, closed=True)
    job_id = await _seed_claimed_job(db_session, sid)
    # key lạ → 401 chuẩn
    r = await client.get(
        f"/api/jobs/{job_id}/status",
        headers={"Authorization": "Bearer totally-random-key"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == BAD_DETAIL
    # session đóng (closed_at set) → 401 CÙNG detail (anti-oracle)
    r = await client.get(
        f"/api/jobs/{job_id}/status",
        headers={"Authorization": f"Bearer {CLOSED_KEY}"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == BAD_DETAIL
    # thiếu header / sai scheme → cùng detail
    r = await client.get(f"/api/jobs/{job_id}/status")
    assert r.status_code == 401
    assert r.json()["detail"] == BAD_DETAIL
    r = await client.get(
        f"/api/jobs/{job_id}/status",
        headers={"Authorization": f"Basic {LIVE_KEY}"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == BAD_DETAIL

async def test_session_key_rate_limit_per_ip(client, db_session):
    sid = await _seed_session(db_session, LIVE_KEY)
    job_id = await _seed_claimed_job(db_session, sid)
    headers = {
        "Authorization": f"Bearer {LIVE_KEY}",
        "X-Forwarded-For": "203.0.113.9",
    }
    ok = 0
    limited = 0
    for _ in range(61):
        r = await client.get(f"/api/jobs/{job_id}/status", headers=headers)
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 429:
            limited += 1
        else:
            raise AssertionError(f"unexpected {r.status_code} {r.text}")
    assert ok == 60 and limited == 1
    # IP khác vẫn 200
    r = await client.get(
        f"/api/jobs/{job_id}/status",
        headers={**headers, "X-Forwarded-For": "203.0.113.10"},
    )
    assert r.status_code == 200, r.text

async def test_runner_key_still_works(worker_client, db_session):
    """get_runner_key path cũ không regress (HTTP worker Colab-loop)."""
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 204  # queue rỗng — runner key được chấp nhận
