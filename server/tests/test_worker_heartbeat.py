"""#7 worker heartbeat: POST /api/worker/heartbeat upsert + GET /api/admin/workers."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import Job, User, WorkerHeartbeat
from app.services.kaggle_orchestrator import _touch_batch_heartbeat


async def test_heartbeat_requires_runner_key(client):
    r = await client.post("/api/worker/heartbeat", json={"worker_id": "w1"})
    assert r.status_code == 401


async def test_heartbeat_upsert_updates_last_seen(worker_client, db_session):
    body = {"worker_id": "colab-1", "current_job_id": None}
    r = await worker_client.post("/api/worker/heartbeat", json=body)
    assert r.status_code == 200, r.text
    first = await db_session.get(WorkerHeartbeat, "colab-1")
    assert first is not None and first.kind == "loop"
    first_seen = first.last_seen
    r = await worker_client.post(
        "/api/worker/heartbeat",
        json={"worker_id": "colab-1", "current_job_id": 7},
    )
    assert r.status_code == 200
    db_session.expire_all()
    rows = (
        await db_session.execute(select(WorkerHeartbeat))
    ).scalars().all()
    assert len(rows) == 1  # upsert, không insert thêm
    row = rows[0]
    assert row.current_job_id == 7  # update đè
    assert row.last_seen >= first_seen


async def test_admin_workers_requires_admin(auth_client):
    assert (await auth_client.get("/api/admin/workers")).status_code == 403


async def test_admin_workers_silent_derived_and_queue_depth(
    admin_client, db_session
):
    user = User(email="hb@test.io", password_hash="x", role="user")
    db_session.add(user)
    await db_session.commit()
    db_session.add(Job(user_id=user.id, status="queued",
                       storage_key="uploads/x.jpg", file_type="image",
                       page_count=1))
    stale = datetime.now(timezone.utc) - timedelta(seconds=90)
    db_session.add(WorkerHeartbeat(worker_id="old-1", kind="loop",
                                   last_seen=stale, current_job_id=None))
    await db_session.commit()

    b = (await admin_client.get("/api/admin/workers")).json()
    row = next(x for x in b["items"] if x["worker_id"] == "old-1")
    assert row["silent_seconds"] >= 89  # derived từ last_seen
    assert b["queue_depth"] == 1


async def test_batch_marker_upsert(db_session):
    """Orchestrator spawn/poll → row kind=kaggle-batch (upsert)."""
    await _touch_batch_heartbeat(SessionLocal, current_job_id=42)
    await _touch_batch_heartbeat(SessionLocal, current_job_id=None)
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(WorkerHeartbeat).where(
                WorkerHeartbeat.worker_id == "kaggle-batch"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "kaggle-batch"
    assert rows[0].current_job_id is None  # update đè

# --- review r1 P2: 422 tách worker_id vs kind -------------------------------

async def test_heartbeat_422_separates_worker_id_and_kind(worker_client):
    r = await worker_client.post(
        "/api/worker/heartbeat", json={"worker_id": "   "}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "worker_id không hợp lệ."
    r = await worker_client.post(
        "/api/worker/heartbeat",
        json={"worker_id": "w1", "kind": "k" * 21},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "kind không hợp lệ."

# --- review r1 P2: silent_seconds naive-safe + clamp 0 -----------------------

def test_silent_seconds_naive_utc_and_future_clamped():
    from app.routers.admin import _silent_seconds

    now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    # naive = UTC (legacy row đọc khỏi DB không offset) → không crash
    assert _silent_seconds(datetime(2026, 10, 14, 11, 59, 30), now) == 30
    # clock skew: last_seen tương lai → 0, không âm
    assert _silent_seconds(now + timedelta(seconds=5), now) == 0

async def test_admin_workers_last_seen_rfc3339_string(admin_client, db_session):
    """Pin: last_seen ra JSON là ISO-8601 string có offset (timezone-aware)."""
    stale = datetime.now(timezone.utc) - timedelta(seconds=30)
    db_session.add(
        WorkerHeartbeat(
            worker_id="iso-1", kind="loop", last_seen=stale, current_job_id=None
        )
    )
    await db_session.commit()
    row = next(
        x
        for x in (await admin_client.get("/api/admin/workers")).json()["items"]
        if x["worker_id"] == "iso-1"
    )
    assert isinstance(row["last_seen"], str)
    assert datetime.fromisoformat(row["last_seen"]).utcoffset() is not None
