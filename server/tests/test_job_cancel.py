"""POST /api/jobs/{id}/cancel — owner hủy job (spec: queued|extracting|
rendering → cancelled terminal; extracting thêm kaggle_ref=NULL; rendering
cancel live auto-output task; done|failed|cancelled → 409 "Không hủy được").

Guard verification rides along: _auto_output completion + batch ingest
must never touch a cancelled row.
"""

import json
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.models import Job
from app.services import job_results
from app.services import kaggle_orchestrator as orch

@pytest_asyncio.fixture
async def other_client(app):
    """Second registered+logged-in user (pattern from test_job_retry)."""
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

async def _force_status(db_session, job_id, **values):
    """Uploaded row faked into the phase under test (no worker round-trip)."""
    await db_session.execute(update(Job).where(Job.id == job_id).values(**values))
    await db_session.commit()

async def test_cancel_queued(auth_client, seed_job, db_session):
    r = await auth_client.post(f"/api/jobs/{seed_job}/cancel")
    assert r.status_code == 204 and r.content == b""
    job = await db_session.get(Job, seed_job)
    await db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.finished_at is not None and job.failed_step is None

async def test_cancel_extracting_nulls_kaggle_ref(auth_client, seed_job, db_session):
    await _force_status(
        db_session, seed_job,
        status="extracting", kaggle_ref="testuser/img2text-batch",
    )
    r = await auth_client.post(f"/api/jobs/{seed_job}/cancel")
    assert r.status_code == 204, r.text
    job = await db_session.get(Job, seed_job)
    await db_session.refresh(job)
    # kaggle_ref NULL = restart không adopt lại batch run cho job này
    assert job.status == "cancelled" and job.kaggle_ref is None

class _FakeTask:
    """Giả asyncio.Task trong _active_outputs (single-flight registry)."""

    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True

async def test_cancel_rendering_cancels_active_output_task(
    auth_client, seed_job, db_session
):
    await _force_status(db_session, seed_job, status="rendering")
    fake = _FakeTask()
    job_results._active_outputs[seed_job] = fake
    try:
        r = await auth_client.post(f"/api/jobs/{seed_job}/cancel")
        assert r.status_code == 204, r.text
        assert fake.cancelled is True
    finally:
        job_results._active_outputs.pop(seed_job, None)
    job = await db_session.get(Job, seed_job)
    await db_session.refresh(job)
    assert job.status == "cancelled"

async def test_cancel_done_409(auth_client, done_job_with_result, db_session):
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/cancel")
    assert r.status_code == 409 and r.json()["detail"] == "Không hủy được"
    job = await db_session.get(Job, done_job_with_result)
    await db_session.refresh(job)
    assert job.status == "done"

async def test_cancel_cancelled_409(auth_client, seed_job, db_session):
    await _force_status(db_session, seed_job, status="cancelled")
    r = await auth_client.post(f"/api/jobs/{seed_job}/cancel")
    assert r.status_code == 409 and r.json()["detail"] == "Không hủy được"

async def test_cancel_unknown_404(auth_client):
    assert (await auth_client.post("/api/jobs/999999/cancel")).status_code == 404

async def test_cancel_other_user_403(other_client, auth_client, seed_job):
    assert (await other_client.post(f"/api/jobs/{seed_job}/cancel")).status_code == 403

async def test_auto_output_completion_never_overwrites_cancelled(
    auth_client, seed_job, db_session
):
    # extract_only: completion path chạy không cần storage/layout — WHERE
    # status IN (rendering, failed) guard check thuần.
    await _force_status(db_session, seed_job, status="cancelled", mode="extract_only")
    job = await db_session.get(Job, seed_job)
    await db_session.refresh(job)
    await job_results._auto_output(job, None)
    await db_session.refresh(job)
    assert job.status == "cancelled" and job.finished_at is None

async def test_ingest_batch_result_skips_cancelled(
    auth_client, seed_job, db_session, tmp_path
):
    await _force_status(db_session, seed_job, status="cancelled")
    (tmp_path / f"{seed_job}_result.json").write_text(
        json.dumps({}), encoding="utf-8"
    )
    await orch._ingest_batch_result(SessionLocal, seed_job, tmp_path)
    job = await db_session.get(Job, seed_job)
    await db_session.refresh(job)
    assert job.status == "cancelled" and job.result is None
