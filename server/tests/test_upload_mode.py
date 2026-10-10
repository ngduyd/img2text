"""Phase 5 (spec E): upload `mode` → jobs.mode; extract_only skips auto-gen layout.

Covers: default layout stored / extract_only stored / invalid → 422,
extract_only result → done with NO exports/{id}/ artifact (worker + batch
paths), auto_generate_output returns False for extract_only.
"""

from datetime import datetime, timezone

from app.core.models import Job
from app.core.schemas import ResultBody
from app.services.job_results import drain_auto_output, store_batch_result

from tests.test_upload import TEST_JPEG  # noqa: F401 (reuses fixtures via conftest)


async def _upload(auth_client, mode: str | None = None):
    data = {"mode": mode} if mode else {}
    return await auth_client.post(
        "/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/png")}, data=data
    )


async def test_upload_defaults_to_layout_mode(auth_client, db_session):
    r = await _upload(auth_client)
    assert r.status_code == 201
    job = await db_session.get(Job, r.json()["id"])
    assert job.mode == "layout"


async def test_upload_extract_only_stored(auth_client, db_session):
    r = await _upload(auth_client, "extract_only")
    assert r.status_code == 201
    job = await db_session.get(Job, r.json()["id"])
    assert job.mode == "extract_only"


async def test_upload_invalid_mode_422(auth_client):
    r = await _upload(auth_client, "pdf")
    assert r.status_code == 422
    assert r.json()["detail"] == "Chế độ xử lý không hợp lệ."


async def test_extract_only_result_skips_layout_gen(
    auth_client, worker_client, storage_spy, db_session, VALID_RESULT_JSONB
):
    """Worker path: OCR done → job done, NO exports/{id}/ artifact."""
    r = await _upload(auth_client, "extract_only")
    jid = r.json()["id"]
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{jid}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    keys = [c.args[0] for c in storage_spy.put.await_args_list]
    assert not any(k.startswith(f"exports/{jid}/") for k in keys)
    db_session.expire_all()  # identity map may hold the pre-UPDATE instance
    job = await db_session.get(Job, jid)
    assert job.status == "done" and job.failed_step is None


async def test_store_batch_result_extract_only_no_layout(
    db_session, auth_client, storage_spy, VALID_RESULT_JSONB
):
    """Kaggle ingest path: extract_only → done, no layout artifact."""
    r = await _upload(auth_client, "extract_only")
    jid = r.json()["id"]
    body = ResultBody.model_validate(VALID_RESULT_JSONB)
    assert (
        await store_batch_result(
            db_session,
            jid,
            body,
            now=datetime.now(timezone.utc),
            storage=storage_spy,
        )
        is True
    )
    await drain_auto_output()
    keys = [c.args[0] for c in storage_spy.put.await_args_list]
    assert not any(k.startswith(f"exports/{jid}/") for k in keys)
    db_session.expire_all()  # identity map may hold the pre-UPDATE instance
    job = await db_session.get(Job, jid)
    assert job.status == "done"
