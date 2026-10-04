"""Task 5 (Plan B): lease reaper wiring + heartbeat atomicity (R17)."""

from datetime import datetime, timedelta, timezone

from app.models import Job

async def test_scheduler_job_registered(app):
    from app.scheduler import init_scheduler

    scheduler = init_scheduler(app)  # lifespan skipped under ASGITransport
    jobs = [j for j in scheduler.get_jobs() if j.id == "reap-leases"]
    assert len(jobs) == 1

async def test_reap_leases_requeues_expired_and_reclaimable(
    worker_client, db_session, seed_job
):
    from app.jobs_requeue import reap_leases

    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200
    tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    assert await reap_leases(db_session) == 1
    job = await db_session.get(Job, seed_job)
    assert job.status == "queued" and job.worker_token is None
    assert job.started_at is None and job.lease_expires_at is None
    # reclaimable: /next claims the requeued job again
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200 and r.json()["job_id"] == seed_job
    assert r.json()["worker_token"] and r.json()["worker_token"] != tok

async def test_heartbeat_expired_lease_409_extends_nothing(
    worker_client, db_session, seed_job
):
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/heartbeat",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 409
    await db_session.refresh(job)
    assert job.lease_expires_at is not None
    assert job.lease_expires_at < datetime.now(timezone.utc)  # not extended

async def test_next_nonascii_auth_401(worker_client, seed_job):
    """Task 4 isascii guard: non-ascii bearer token → 401, not 500."""
    r = await worker_client.get(
        "/api/jobs/next", headers={"Authorization": b"Bearer t\xebst-key"}
    )
    assert r.status_code == 401
