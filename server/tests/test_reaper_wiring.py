"""Task 5 (Plan B): lease reaper wiring + heartbeat atomicity (R17).

Review P1: stale-rendering sweep — a server death between the result
commit and the fire-and-forget auto-output completion loses the task;
the next tick re-schedules it."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import Job

async def test_scheduler_job_registered(app):
    from app.services.scheduler import init_scheduler

    scheduler = init_scheduler(app)  # lifespan skipped under ASGITransport
    jobs = [j for j in scheduler.get_jobs() if j.id == "reap-leases"]
    assert len(jobs) == 1
    # wave-5 S1: purge-storage hourly
    purge = [j for j in scheduler.get_jobs() if j.id == "purge-storage"]
    assert len(purge) == 1

async def test_reap_leases_requeues_expired_and_reclaimable(
    worker_client, db_session, seed_job
):
    from app.services.jobs_requeue import reap_leases

    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200
    tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    assert await reap_leases(db_session) == 1
    job = await db_session.get(Job, seed_job)
    assert job.status == "queued" and job.worker_token_hash is None
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
    old_lease = job.lease_expires_at
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/heartbeat",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 409
    await db_session.refresh(job)
    # strengthened: capture lease before heartbeat → unchanged after 409
    assert job.lease_expires_at == old_lease
    assert job.lease_expires_at < datetime.now(timezone.utc)  # not extended

# --- P1: stale rendering sweep ---

@pytest.fixture(autouse=True)
def _clean_active_outputs():
    """Registry is process-global; drain stragglers around each test."""
    from app.services import job_results
    job_results._active_outputs.clear()
    yield
    job_results._active_outputs.clear()

async def _stale_rendering_job(db_session, seed_job, VALID_RESULT_JSONB, *, age):
    job = await db_session.get(Job, seed_job)
    job.status = "rendering"
    job.result = VALID_RESULT_JSONB
    job.failed_step = None
    job.started_at = datetime.now(timezone.utc) - age
    await db_session.commit()
    return seed_job

async def test_sweep_rendering_reschedules_stale_job(
    app, db_session, seed_job, VALID_RESULT_JSONB, monkeypatch
):
    """Crash sim: task lost mid auto_generate_output → tick re-schedules →
    new task runs → done."""
    from app.services import job_results
    from app.services.scheduler import _run_jobs_once

    job_id = await _stale_rendering_job(
        db_session, seed_job, VALID_RESULT_JSONB, age=timedelta(minutes=10)
    )
    assert job_id not in job_results._active_outputs  # task lost with the process
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    await _run_jobs_once(app.state.storage)
    assert job_id in job_results._active_outputs  # NEW task scheduled
    await job_results.drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, job_id)
    assert job.status == "done" and job.failed_step is None

async def test_sweep_rendering_covers_null_started_at(
    app, db_session, seed_job, VALID_RESULT_JSONB, monkeypatch
):
    """Batch ingest từ queued → started_at NULL → SQL NULL < cutoff never
    true → MUST still sweep (cùng class bug P1: kẹt forever)."""
    from app.services import job_results
    from app.services.scheduler import _run_jobs_once

    job_id = await _stale_rendering_job(
        db_session, seed_job, VALID_RESULT_JSONB, age=timedelta(minutes=10)
    )
    job = await db_session.get(Job, job_id)
    job.started_at = None  # queued-direct ingest path
    await db_session.commit()

    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    await _run_jobs_once(app.state.storage)
    assert job_id in job_results._active_outputs  # swept despite NULL
    await job_results.drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, job_id)
    assert job.status == "done"

async def test_sweep_rendering_one_task_per_job_and_skips_fresh(
    app, db_session, seed_job, VALID_RESULT_JSONB, monkeypatch
):
    """Guard: a second tick while the first task is live schedules nothing;
    a fresh rendering row (task may vanish any second) is left alone."""
    from app.services import job_results
    from app.services.scheduler import _run_jobs_once

    job_id = await _stale_rendering_job(
        db_session, seed_job, VALID_RESULT_JSONB, age=timedelta(minutes=10)
    )
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    await _run_jobs_once(app.state.storage)
    first = job_results._active_outputs.get(job_id)
    assert first is not None
    await _run_jobs_once(app.state.storage)  # second tick, task still live
    assert job_results._active_outputs.get(job_id) is first  # same task, no dup
    await job_results.drain_auto_output()
    # fresh rendering row → untouched
    job = await db_session.get(Job, job_id)
    job.status = "rendering"
    job.started_at = datetime.now(timezone.utc)  # just entered rendering
    await db_session.commit()
    await _run_jobs_once(app.state.storage)
    assert job_id not in job_results._active_outputs

async def test_next_nonascii_auth_401(worker_client, seed_job):
    """Task 4 isascii guard: non-ascii bearer token → 401, not 500."""
    r = await worker_client.get(
        "/api/jobs/next", headers={"Authorization": b"Bearer t\xebst-key"}
    )
    assert r.status_code == 401
