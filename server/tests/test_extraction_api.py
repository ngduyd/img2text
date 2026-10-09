"""Phase 1 Task 4: extraction API (save text + sync + conflict + restore)."""

from app.services.doc_versions import save_version


async def _seed_layouts(app, job_id: int) -> None:
    s = app.state.storage
    await s.put(f"exports/{job_id}/md-layout", b"# Tieu de\n\nXin chao the gioi")
    await s.put(f"exports/{job_id}/docx.html", b"<p>Xin chao <b>the gioi</b></p>")


async def test_get_extraction_lazy_seed(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    r = await auth_client.get(f"/api/jobs/{jid}/extraction")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "Xin chào\n"
    assert body["text_version"] == 0
    r2 = await auth_client.get(f"/api/jobs/{jid}/versions?kind=text")
    assert len(r2.json()["items"]) == 1  # lazy-seeded v1
    assert r2.json()["items"][0]["version"] == 1


async def test_post_extraction_save_sync_200(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "Xin chao ban",
            "old_phrase": "Xin chao",
            "new_phrase": "Xin chao ban",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synced"] == {"md": True, "docx": True}
    assert body["needs_render"] == []
    assert body["text_version"] == 1
    st = app.state.storage
    assert b"Xin chao ban" in await st.get(f"exports/{jid}/md-layout")
    assert b"<b>the gioi</b>" in await st.get(f"exports/{jid}/docx.html")
    r2 = await auth_client.get(f"/api/jobs/{jid}/extraction")
    assert r2.json() == {"text": "Xin chao ban", "text_version": 1}


async def test_post_extraction_version_mismatch_409(auth_client, done_job_with_result):
    jid = done_job_with_result
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "x", "expected_text_version": 5},
    )
    assert r.status_code == 409


async def test_post_extraction_detached_conflict_409(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    await save_version(
        app.state.storage, jid, "md-layout", b"# mine", 0, detached=True
    )
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "text moi",
            "old_phrase": "Xin chao",
            "new_phrase": "text",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 409
    st = app.state.storage
    assert await st.get(f"exports/{jid}/md-layout") == b"# Tieu de\n\nXin chao the gioi"
    # user confirms → force overwrites, detached cleared
    r2 = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "text moi",
            "old_phrase": "Xin chao",
            "new_phrase": "text moi",
            "expected_text_version": 0,
            "force": True,
        },
    )
    assert r2.status_code == 200, r2.text
    assert b"text moi" in await st.get(f"exports/{jid}/md-layout")
    r3 = await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    newest = r3.json()["items"][0]
    assert newest["detached"] is False


async def test_post_extraction_needs_render(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    await app.state.storage.put(f"exports/{jid}/md-layout", b"# Tieu de")
    await app.state.storage.put(f"exports/{jid}/docx.html", b"<p>doc dac biet</p>")
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "dac biet",
            "old_phrase": "dac biet",
            "new_phrase": "x",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == {"md": False, "docx": True}
    assert r.json()["needs_render"] == ["md-layout"]


async def test_restore_text_appends_version(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "ban 1", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "ban 2", "expected_text_version": 1},
    )
    assert r.status_code == 200, r.text
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=text")).json()["items"]
    v1 = [i for i in items if i["version"] == 1][0]
    r = await auth_client.post(f"/api/jobs/{jid}/versions/{v1['id']}/restore")
    assert r.status_code == 204, r.text
    got = (await auth_client.get(f"/api/jobs/{jid}/extraction")).json()
    assert got == {"text": "ban 1", "text_version": 3}  # restore bumps
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=text")).json()["items"]
    assert [i["version"] for i in items] == [3, 2, 1]  # append-only


async def test_restore_layout_writes_artifact(auth_client, app, done_job_with_result):
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    # GET first → lazy-seed v1 = original artifact, sync below makes v2
    assert (await auth_client.get(f"/api/jobs/{jid}/extraction")).status_code == 200
    await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "sua md",
            "old_phrase": "Xin chao the gioi",
            "new_phrase": "sua md",
            "expected_text_version": 0,
        },
    )
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")).json()["items"]
    v1 = [i for i in items if i["version"] == 1][0]
    r = await auth_client.post(f"/api/jobs/{jid}/versions/{v1['id']}/restore")
    assert r.status_code == 204, r.text
    assert await app.state.storage.get(f"exports/{jid}/md-layout") == \
        b"# Tieu de\n\nXin chao the gioi"
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")).json()["items"]
    assert [i["version"] for i in items] == [3, 2, 1]  # seed v1, sync v2, restore v3


async def test_put_layout_marks_detached(auth_client, done_job_with_result):
    """Task 6: direct layout edit → latest snapshot detached=True."""
    jid = done_job_with_result
    r = await auth_client.put(
        f"/api/jobs/{jid}/export/md-layout/content", json={"markdown": "# sua tay"}
    )
    assert r.status_code == 204, r.text
    r = await auth_client.put(
        f"/api/jobs/{jid}/export/docx-layout/html", json={"html": "<p>sua tay</p>"}
    )
    assert r.status_code == 204, r.text
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")).json()["items"]
    assert items[0]["detached"] is True
    items = (await auth_client.get(f"/api/jobs/{jid}/versions?kind=docx-layout")).json()["items"]
    assert items[0]["detached"] is True
