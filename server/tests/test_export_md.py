"""Plan D Task 1: POST /api/jobs/{id}/export md branch tests (brief exact)."""

async def test_export_md_returns_presigned_and_caches(auth_client, done_job_with_result, storage_spy):
    r1 = await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    assert r1.status_code == 200 and "exports/" in r1.json()["url"]
    calls_after_first = storage_spy.put.call_count
    r2 = await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    assert r2.status_code == 200 and storage_spy.put.call_count == calls_after_first  # cache hit

async def test_export_uses_edited_markdown(auth_client, done_job_with_result, storage):
    await auth_client.patch(f"/api/jobs/{done_job_with_result}/content", json={"markdown": "# EDITED"})
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md"})
    body = await storage.get(f"exports/{done_job_with_result}/md")
    assert body == b"# EDITED"

async def test_export_409_when_not_done(auth_client, seed_job):
    r = await auth_client.post(f"/api/jobs/{seed_job}/export", json={"fmt": "md"})
    assert r.status_code == 409
