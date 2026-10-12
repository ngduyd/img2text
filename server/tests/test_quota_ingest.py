"""#6 quota chống khai láo: ingest ghi page_count THẬT → GET /api/quota/me."""

from copy import deepcopy

from app.core.models import Job
from app.services.job_results import drain_auto_output, store_batch_result
from tests.conftest import TEST_PDF_3, upload_job


def _result_3_pages(base: dict) -> dict:
    body = deepcopy(base)
    body["pages"] = [
        {**deepcopy(base["pages"][0]), "index": i} for i in range(3)
    ]
    return body


async def test_loop_ingest_page_count_then_quota_me(
    auth_client, storage, worker_client, db_session,
    VALID_RESULT_JSONB, monkeypatch,
):
    """Create khai 1 trang → worker ingest 3 pages → quota daily_used=3."""
    async def _md_ok(*args, **kwargs):
        return "# layout md"

    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    r = await upload_job(
        auth_client, storage, TEST_PDF_3, "a.pdf", page_count=1
    )
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    q = (await auth_client.get("/api/quota/me")).json()
    assert q["daily_used"] == 1  # khai báo 1 trang

    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{job_id}/result",
        json=_result_3_pages(VALID_RESULT_JSONB),
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    await drain_auto_output()

    db_session.expire_all()
    job = await db_session.get(Job, job_id)
    assert job.page_count == 3  # số trang THẬT từ OCR result
    q = (await auth_client.get("/api/quota/me")).json()
    assert q["daily_used"] == 3


async def test_batch_ingest_page_count(db_session, VALID_RESULT_JSONB):
    """Batch path (_ingest_batch_result → store_batch_result): page_count=3."""
    from datetime import datetime, timezone

    from app.core.models import User
    from app.core.schemas import ResultBody

    user = User(email="b@test.io", password_hash="x", role="user")
    db_session.add(user)
    await db_session.commit()
    job = Job(
        user_id=user.id, status="queued", storage_key="uploads/x.pdf",
        file_type="pdf", page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    job_id = job.id

    ok = await store_batch_result(
        db_session, job_id, ResultBody.model_validate(_result_3_pages(VALID_RESULT_JSONB)),
        now=datetime.now(timezone.utc),
    )
    assert ok
    db_session.expire_all()
    fresh = await db_session.get(Job, job_id)
    assert fresh.page_count == 3
