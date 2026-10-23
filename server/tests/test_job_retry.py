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
async def done_job_with_result(worker_client, seed_job, VALID_RESULT_JSONB, monkeypatch) -> int:
    """Owner-uploaded job completed via the worker protocol → done
    (auto-output drained; one layout OK per the completion rule)."""
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    claim = await worker_client.get("/api/jobs/next")
    assert claim.status_code == 200 and claim.json()["job_id"] == seed_job
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {claim.json()['worker_token']}"},
    )
    assert r.status_code == 200, r.text
    from app.services.job_results import drain_auto_output
    await drain_auto_output()
    return seed_job

async def test_retry_failed_requeues(auth_client, failed_job, db_session):
    # spec 2026-10-09: success is 204 (no body) — was 200 + {id, status}
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 204 and r.content == b""
    job = await db_session.get(Job, failed_job)
    assert job.status == "queued" and job.error is None
    assert job.failed_step is None  # retry target cleared with the requeue
    assert job.worker_token_hash is None and job.lease_expires_at is None
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
    assert r.status_code == 204
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200 and r.json()["job_id"] == failed_job

async def test_retry_invalidates_both_prefixes(auth_client, failed_job, storage_spy):
    """Binding (Plan D): BOTH exports/{id}/ and crops/{id}/ deleted on retry."""
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 204
    storage_spy.delete_prefix.assert_any_call(f"exports/{failed_job}/")
    storage_spy.delete_prefix.assert_any_call(f"crops/{failed_job}/")

# --- Retry layout gen: POST /api/jobs/{id}/retry-layout ---

async def test_retry_layout_regenerates(auth_client, done_job_with_result, storage, monkeypatch):
    """retry-layout re-runs auto_generate_output; returns which layouts exist."""
    # Drain the fire-and-forget auto-output scheduled at result-commit, then
    # clear its artifacts: job ids restart at 1 after truncate, so a prior
    # test's exports/{id}/ would otherwise leak into this one.
    from app.services.job_results import drain_auto_output
    await drain_auto_output()
    await storage.delete_prefix(f"exports/{done_job_with_result}/")
    called = {}
    async def fake_auto(job, storage):
        called["job_id"] = job.id
        await storage.put(f"exports/{job.id}/md-layout", b"# md")
    monkeypatch.setattr("app.routers.exports.auto_generate_output", fake_auto)
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/retry-layout")
    assert r.status_code == 200
    assert r.json() == {"md": True, "docx": False}
    assert called["job_id"] == done_job_with_result

async def test_retry_layout_works_when_queued(auth_client, seed_job, storage, monkeypatch):
    """Layout gen is post-OCR fire-and-forget: no status gate (queued → 200)."""
    from app.services.job_results import drain_auto_output
    await drain_auto_output()
    await storage.delete_prefix(f"exports/{seed_job}/")
    async def fake_auto(job, storage):
        pass
    monkeypatch.setattr("app.routers.exports.auto_generate_output", fake_auto)
    r = await auth_client.post(f"/api/jobs/{seed_job}/retry-layout")
    assert r.status_code == 200
    assert r.json() == {"md": False, "docx": False}

async def test_retry_layout_unknown_404(auth_client):
    assert (await auth_client.post("/api/jobs/999999/retry-layout")).status_code == 404

async def test_retry_layout_other_user_403(other_client, done_job_with_result):
    assert (await other_client.post(f"/api/jobs/{done_job_with_result}/retry-layout")).status_code == 403


# --- Lane S Task 3: retry-layout → docx-layout thật sự được ghi (S5) ---

async def test_retry_layout_writes_docx_layout(
    auth_client, done_job_with_result, storage
):
    """retry-layout (0 LLM) → exports/{id}/docx-layout được put (wiring thật,
    không monkeypatch auto_generate_output)."""
    from app.services.job_results import drain_auto_output

    await drain_auto_output()
    await storage.delete_prefix(f"exports/{done_job_with_result}/")

    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/retry-layout")
    assert r.status_code == 200, r.text
    assert r.json()["docx"] is True
    body = await storage.get(f"exports/{done_job_with_result}/docx-layout")
    assert body[:2] == b"PK"
