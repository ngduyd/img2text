"""Lane B3 (S4): GET /api/admin/storage stats+list + POST purge-due.

due_jobs = đúng predicate purge batch (done + cũ hơn retention + auto_purge +
chưa purge) — số việc "Dọn file hết hạn" sẽ thật sự làm.
"""

from datetime import datetime, timedelta, timezone

from app.core.models import Job, User
from tests.conftest import TEST_JPEG, upload_job

OLD = datetime.now(timezone.utc) - timedelta(days=10)
RECENT = datetime.now(timezone.utc) - timedelta(hours=1)

async def _seed(db_session, *, auto_purge: bool = True) -> dict:
    """1 user; jobs: old done (due), old done purged, recent done, old queued."""
    u = User(
        email="owner@test.io",
        password_hash="x",
        role="user",
        auto_purge=auto_purge,
    )
    db_session.add(u)
    await db_session.flush()

    def job(**kw) -> Job:
        kw.setdefault("status", "done")
        return Job(
            user_id=u.id,
            storage_key="k",
            file_type="png",
            page_count=1,
            filename="a.png",
            upload_bytes=100,
            **kw,
        )

    due = job(created_at=OLD)
    purged = job(created_at=OLD, storage_purged_at=OLD)
    recent = job(created_at=RECENT)
    queued = job(created_at=OLD, status="queued")
    db_session.add_all([due, purged, recent, queued])
    await db_session.commit()
    return {"due": due.id, "purged": purged.id, "recent": recent.id, "queued": queued.id}

async def test_storage_stats(admin_client, db_session):
    ids = await _seed(db_session)
    r = await admin_client.get("/api/admin/storage")
    assert r.status_code == 200, r.text
    s = r.json()["stats"]
    assert s["total_jobs"] == 4
    assert s["purged_jobs"] == 1
    assert s["due_jobs"] == 1
    assert s["total_upload_bytes"] == 400
    assert s["purged_bytes"] == 100

async def test_storage_stats_due_respects_auto_purge_off(admin_client, db_session):
    await _seed(db_session, auto_purge=False)
    s = (await admin_client.get("/api/admin/storage")).json()["stats"]
    assert s["due_jobs"] == 0  # auto_purge=false → scheduler không đụng

async def test_storage_list_old_jobs_paged(admin_client, db_session):
    ids = await _seed(db_session)
    body = (await admin_client.get("/api/admin/storage?page=1&size=2")).json()
    # list = jobs CŨ (cả queued, cả purged) — không gồm recent
    assert body["total"] == 3
    assert len(body["items"]) == 2
    item = next(i for i in body["items"] if i["id"] == ids["due"])
    assert item["email"] == "owner@test.io"
    assert item["filename"] == "a.png"
    assert item["upload_bytes"] == 100
    assert item["storage_purged_at"] is None
    assert item["auto_purge"] is True
    page2 = (await admin_client.get("/api/admin/storage?page=2&size=2")).json()
    assert len(page2["items"]) == 1

async def test_storage_admin_only(auth_client, db_session):
    assert (await auth_client.get("/api/admin/storage")).status_code == 403
    assert (await auth_client.post("/api/admin/storage/purge-due")).status_code == 403

async def test_purge_due_runs_now(admin_client, app, db_session):
    await _seed(db_session)
    r = await upload_job(admin_client, app.state.storage, TEST_JPEG, "old.jpg")
    assert r.status_code == 201, r.text
    old_id = r.json()["id"]
    j = await db_session.get(Job, old_id)
    j.created_at = OLD
    j.status = "done"
    await db_session.commit()
    await app.state.storage.put(f"exports/{old_id}/pdf", b"%PDF")

    r = await admin_client.post("/api/admin/storage/purge-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"purged": 2}  # seeded due + uploaded old
    await db_session.refresh(j)
    assert j.storage_purged_at is not None
    assert not await app.state.storage.exists(f"exports/{old_id}/pdf")
    # due đã purge → lần sau 0 (idempotent)
    r = await admin_client.post("/api/admin/storage/purge-due")
    assert r.json() == {"purged": 0}
    # stats phản ánh: purged_jobs = 3 (purged seed + due seed + old_id)
    s = (await admin_client.get("/api/admin/storage")).json()["stats"]
    assert s["purged_jobs"] == 3
    assert s["due_jobs"] == 0
