"""Plan Task 3: unified per-step retry — POST /api/jobs/{id}/retry.

failed + failed_step="extracting" (or NULL) → 204 + queued (respawn next
orchestrator tick); failed + failed_step="rendering" → 204, layout re-run
flip to done; anything else → 409; unknown → 404; authz strict owner.
"""

import pytest_asyncio

from app.core.models import Job

from tests.test_job_retry import other_client  # noqa: F401 (403 fixture)

@pytest_asyncio.fixture
async def failed_extracting_job(worker_client, seed_job) -> int:
    """Realistic failure through the worker protocol → failed + extracting."""
    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200 and claim.json()["job_id"] == seed_job
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/fail",
        json={"error": "boom"},
        headers={"Authorization": f"Bearer {claim.json()['worker_token']}"},
    )
    assert r.status_code == 200, r.text
    return seed_job

@pytest_asyncio.fixture
async def failed_rendering_job(db_session, seed_job, VALID_RESULT_JSONB) -> int:
    """Auto-gen failure state: OCR result stored, status failed + rendering."""
    job = await db_session.get(Job, seed_job)
    job.status = "failed"
    job.failed_step = "rendering"
    job.result = VALID_RESULT_JSONB
    await db_session.commit()
    return seed_job

async def test_retry_extracting_requeues_204(auth_client, failed_extracting_job, db_session):
    r = await auth_client.post(f"/api/jobs/{failed_extracting_job}/retry")
    assert r.status_code == 204 and r.content == b""
    db_session.expire_all()
    job = await db_session.get(Job, failed_extracting_job)
    assert job.status == "queued"
    assert job.failed_step is None and job.error is None
    assert job.lease_expires_at is None

async def test_retry_rendering_reruns_layout_to_done(
    auth_client, failed_rendering_job, db_session, monkeypatch
):
    """failed+rendering → 204 (stays failed while in flight) → auto-output
    completion flips to done (≥1 layout OK)."""
    async def _md_ok(*args, **kwargs):
        return "# layout md"

    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    r = await auth_client.post(f"/api/jobs/{failed_rendering_job}/retry")
    assert r.status_code == 204 and r.content == b""  # bare 204, no body
    from app.services.job_results import drain_auto_output
    await drain_auto_output()
    db_session.expire_all()
    job = await db_session.get(Job, failed_rendering_job)
    assert job.status == "done" and job.failed_step is None
    assert job.finished_at is not None

async def test_retry_queued_409(auth_client, seed_job):
    r = await auth_client.post(f"/api/jobs/{seed_job}/retry")
    assert r.status_code == 409 and r.json()["detail"] == "job not retryable"

async def test_retry_done_409(auth_client, done_job_with_result):
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/retry")
    assert r.status_code == 409 and r.json()["detail"] == "job not retryable"

async def test_retry_unknown_404(auth_client):
    r = await auth_client.post("/api/jobs/999999/retry")
    assert r.status_code == 404 and r.json()["detail"] == "job not found"

async def test_retry_other_user_403(other_client, failed_extracting_job):
    assert (
        await other_client.post(f"/api/jobs/{failed_extracting_job}/retry")
    ).status_code == 403
