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

async def test_patch_content_bumps_text_version(auth_client, done_job_with_result, db_session):
    """P1-2: content edit → bump jobs.text_version (stale badge) + text
    snapshot kind "text" (lịch sử thấy edit)."""
    jid = done_job_with_result
    r = await auth_client.patch(f"/api/jobs/{jid}/content", json={"markdown": "# moi"})
    assert r.status_code == 200, r.text
    job = await db_session.get(Job, jid)
    await db_session.refresh(job)
    assert job.text_version == 1
    items = (await auth_client.get(
        f"/api/jobs/{jid}/versions", params={"kind": "text"}
    )).json()["items"]
    assert items and items[0]["based_on_text_version"] == 1
