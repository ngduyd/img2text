"""Wave-3 Lane G: PATCH /api/jobs/{id}/layout-content — layout edit (md pane).

Covers: 200 {ok:true} + upsert exports/{id}/md-layout + snapshot trước/sau kind
md-layout (seed v1 = artifact cũ, v2 = bản sửa, detached) + KHÔNG đụng
text_version; empty 422; oversize 422; queued 409; other-user 403.
"""

from tests.test_jobs_read import other_client  # noqa: F401  (fixture)


async def test_ok_snapshot_pre_post_no_text_version_bump(
    auth_client, done_job_with_result, storage
):
    jid = done_job_with_result
    # Artifact hiện tại (bản trước khi user sửa) → seed version 1.
    await storage.put(f"exports/{jid}/md-layout", b"# cu")
    tv_before = (await auth_client.get(f"/api/jobs/{jid}")).json()["text_version"]
    r = await auth_client.patch(
        f"/api/jobs/{jid}/layout-content", json={"markdown": "# moi"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert await storage.get(f"exports/{jid}/md-layout") == b"# moi"
    # KHÔNG đụng text_version (layout artifact = đời sống riêng, spec wave-3).
    assert (
        await auth_client.get(f"/api/jobs/{jid}")
    ).json()["text_version"] == tv_before
    # Snapshot trước/sau: v1 = artifact cũ (không detached), v2 = bản sửa.
    items = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    ).json()["items"]
    assert [v["version"] for v in items] == [2, 1]
    assert [v["detached"] for v in items] == [True, False]
    assert await storage.get(f"versions/{jid}/md-layout/1") == b"# cu"
    assert await storage.get(f"versions/{jid}/md-layout/2") == b"# moi"


async def test_appends_after_prior_put_edit(auth_client, done_job_with_result, storage):
    """PUT route (Plan M) đã ghi version → PATCH append, không đè."""
    jid = done_job_with_result
    await storage.put(f"exports/{jid}/md-layout", b"# cu")
    r = await auth_client.put(
        f"/api/jobs/{jid}/export/md-layout/content", json={"markdown": "# plan-m"}
    )
    assert r.status_code == 204
    r = await auth_client.patch(
        f"/api/jobs/{jid}/layout-content", json={"markdown": "# wave3"}
    )
    assert r.status_code == 200, r.text
    items = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    ).json()["items"]
    # PUT không seed → v1 = "# plan-m" (detached); PATCH đã có version → v2.
    assert [(v["version"], v["detached"]) for v in items] == [(2, True), (1, True)]
    assert await storage.get(f"versions/{jid}/md-layout/1") == b"# plan-m"
    assert await storage.get(f"exports/{jid}/md-layout") == b"# wave3"


async def test_empty_422(auth_client, done_job_with_result):
    r = await auth_client.patch(
        f"/api/jobs/{done_job_with_result}/layout-content", json={"markdown": "  "}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Nội dung trống."


async def test_oversize_422(auth_client, done_job_with_result):
    r = await auth_client.patch(
        f"/api/jobs/{done_job_with_result}/layout-content",
        json={"markdown": "x" * 500_001},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Nội dung quá dài."


async def test_queued_409(auth_client, seed_job):
    r = await auth_client.patch(
        f"/api/jobs/{seed_job}/layout-content", json={"markdown": "# x"}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Chưa có kết quả OCR."


async def test_other_user_403(auth_client, other_client, done_job_with_result):
    r = await other_client.patch(
        f"/api/jobs/{done_job_with_result}/layout-content", json={"markdown": "# x"}
    )
    assert r.status_code == 403
