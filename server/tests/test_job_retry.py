"""Task 4 (Plan E): POST /api/jobs/{id}/retry — owner requeue + cache invalidation.

Binding (Plan D final review): retry must invalidate BOTH storage prefixes —
stale export bytes + old-bbox crops must not survive a re-run.
"""

from uuid import uuid4

import httpx
import pytest_asyncio

from app.core.models import Job

FAILED_ERROR = "boom"

@pytest_asyncio.fixture
async def other_client(app):
    """Second registered+logged-in user; own cookies (pattern from test_jobs_read)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        email = f"other-{uuid4().hex}@test.io"
        r = await c.post(
            "/api/auth/register", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 201, r.text
        r = await c.post(
            "/api/auth/login", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 200, r.text
        yield c

@pytest_asyncio.fixture
async def failed_job(worker_client, seed_job) -> int:
    """Owner-uploaded job, claimed + failed via worker protocol (realistic state)."""
    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200 and claim.json()["job_id"] == seed_job
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/fail",
        json={"error": FAILED_ERROR},
        headers={"Authorization": f"Bearer {claim.json()['worker_token']}"},
    )
    assert r.status_code == 200, r.text
    return seed_job

@pytest_asyncio.fixture
async def done_job_with_result(worker_client, seed_job, VALID_RESULT_JSONB) -> int:
    """Owner-uploaded job completed with a spec-shaped result."""
    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200 and claim.json()["job_id"] == seed_job
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {claim.json()['worker_token']}"},
    )
    assert r.status_code == 200, r.text
    return seed_job

async def test_retry_failed_requeues(auth_client, failed_job, db_session):
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 200 and r.json() == {"id": failed_job, "status": "queued"}
    job = await db_session.get(Job, failed_job)
    assert job.status == "queued" and job.error is None
    assert job.worker_token is None and job.lease_expires_at is None
    assert job.started_at is None and job.finished_at is None

async def test_retry_done_409(auth_client, done_job_with_result):
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/retry")
    assert r.status_code == 409

async def test_retry_unknown_404(auth_client):
    assert (await auth_client.post("/api/jobs/999999/retry")).status_code == 404

async def test_retry_other_user_403(other_client, failed_job):
    assert (await other_client.post(f"/api/jobs/{failed_job}/retry")).status_code == 403

async def test_retried_job_claimable(auth_client, worker_client, failed_job):
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 200
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200 and r.json()["job_id"] == failed_job

async def test_retry_invalidates_both_prefixes(auth_client, failed_job, storage_spy):
    """Binding (Plan D): BOTH exports/{id}/ and crops/{id}/ deleted on retry."""
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 200
    storage_spy.delete_prefix.assert_any_call(f"exports/{failed_job}/")
    storage_spy.delete_prefix.assert_any_call(f"crops/{failed_job}/")
