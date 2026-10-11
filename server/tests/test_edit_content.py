"""Plan D Task 1: PATCH /api/jobs/{id}/content tests (brief exact)."""

from app.core.models import Job

async def test_patch_content_done(auth_client, done_job_with_result, db_session):
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content",
                                json={"markdown": "## Part 2\nEdited."})
    assert r.status_code == 200
    job = await db_session.get(Job, done_job_with_result)
    await db_session.refresh(job)  # request session committed; drop stale identity-map copy
    assert job.result["edited_markdown"] == "## Part 2\nEdited."

async def test_patch_content_returns_text_version(auth_client, done_job_with_result):
    """P2-3: response mang text_version MỚI (bump) — client/API thô biết tv."""
    r = await auth_client.patch(f"/api/jobs/{done_job_with_result}/content",
                                json={"markdown": "# moi"})
    assert r.status_code == 200
    assert r.json()["text_version"] == 1

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

async def test_content_edit_snapshot_bytes_is_saved_markdown(
    auth_client, done_job_with_result, storage
):
    """P1-R3: content edit → v2 snapshot = edited_markdown vừa lưu;
    v1 = bản gốc (regions text)."""
    jid = done_job_with_result
    r = await auth_client.patch(
        f"/api/jobs/{jid}/content", json={"markdown": "# moi"}
    )
    assert r.status_code == 200, r.text
    v2 = (await storage.get(f"versions/{jid}/text/2")).decode("utf-8")
    assert v2 == "# moi"  # RED: đang là extraction_text cũ (bản copy y hệt v1)
    v1 = (await storage.get(f"versions/{jid}/text/1")).decode("utf-8")
    assert "Xin chào" in v1

async def test_content_edit_save_version_fail_keeps_text_version(
    auth_client, done_job_with_result, db_session, monkeypatch
):
    """P1-R2: save_version fail → bump KHÔNG được commit (không 500 + tv tăng)."""
    async def _boom(*args, **kwargs):
        raise RuntimeError("save_version exploded")

    monkeypatch.setattr("app.routers.jobs.save_version", _boom)
    try:
        await auth_client.patch(
            f"/api/jobs/{done_job_with_result}/content", json={"markdown": "# moi"}
        )
    except Exception:
        pass  # 500 trả về hoặc exception lội lên — cả hai đều OK
    job = await db_session.get(Job, done_job_with_result)
    await db_session.refresh(job)
    assert job.text_version == 0  # RED: bump đã commit trước khi save_version nổ
