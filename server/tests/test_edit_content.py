"""Plan D Task 1: PATCH /api/jobs/{id}/content tests (brief exact)."""

from app.core.models import Job

async def test_patch_content_done(auth_client, done_job_with_result, db_session):
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content",
                                json={"markdown": "## Part 2\nEdited."})
    assert r.status_code == 200
    job = await db_session.get(Job, done_job_with_result)
    await db_session.refresh(job)  # request session committed; drop stale identity-map copy
    assert job.result["edited_markdown"] == "## Part 2\nEdited."

async def test_patch_content_409_when_queued(auth_client, seed_job):
    r = await auth_client.patch(f"/api/jobs/{seed_job}/content", json={"markdown": "x"})
    assert r.status_code == 409

async def test_patch_content_422_empty(auth_client, done_job_with_result):
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": ""})
    assert r.status_code == 422

async def test_patch_invalidates_export_cache(auth_client, done_job_with_result, storage_spy):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": "new"})
    storage_spy.delete_prefix.assert_any_call(f"exports/{done_job_with_result}/")
