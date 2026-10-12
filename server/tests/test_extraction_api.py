"""Phase 1 Task 4: extraction API (save text + sync + conflict + restore)."""

import asyncio

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


async def test_post_extraction_empty_old_phrase_skips_sync(
    auth_client, app, done_job_with_result
):
    """P1-1: empty old_phrase → sync skipped, artifact never corrupted."""
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    st = app.state.storage
    md_before = await st.get(f"exports/{jid}/md-layout")
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "Xin chao",
            "old_phrase": "",
            "new_phrase": "y",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == {"md": False, "docx": False}
    assert r.json()["needs_render"] == []
    # "".replace inserts new between EVERY char — artifact must be untouched
    assert await st.get(f"exports/{jid}/md-layout") == md_before
    got = (await auth_client.get(f"/api/jobs/{jid}/extraction")).json()
    assert got["text"] == "Xin chao"  # text still saved
    assert got["text_version"] == 1

async def test_post_extraction_empty_new_phrase_skips_sync(
    auth_client, app, done_job_with_result
):
    """P1-1: empty new_phrase → sync skipped, artifact untouched."""
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    st = app.state.storage
    md_before = await st.get(f"exports/{jid}/md-layout")
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "Xin chao",
            "old_phrase": "Xin chao",
            "new_phrase": "",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == {"md": False, "docx": False}
    assert r.json()["needs_render"] == []
    assert await st.get(f"exports/{jid}/md-layout") == md_before

async def test_post_extraction_concurrent_expected_one_409(
    auth_client, done_job_with_result
):
    """P1-4: conditional UPDATE (rowcount check) — 1 succeed, 1 stale 409."""
    jid = done_job_with_result
    payload = {"text": "ban mot", "expected_text_version": 0}
    r1, r2 = await asyncio.gather(
        auth_client.post(f"/api/jobs/{jid}/extraction", json=payload),
        auth_client.post(f"/api/jobs/{jid}/extraction", json=payload),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]

async def test_patch_content_snapshots_layouts_before_wipe(
    auth_client, app, done_job_with_result
):
    """P1-3: PATCH /content wipe keeps layout bytes in version history."""
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    r = await auth_client.patch(
        f"/api/jobs/{jid}/content", json={"markdown": "# moi"}
    )
    assert r.status_code == 200, r.text
    for kind, expect in (
        ("md-layout", b"# Tieu de\n\nXin chao the gioi"),
        ("docx-layout", b"<p>Xin chao <b>the gioi</b></p>"),
    ):
        items = (
            await auth_client.get(f"/api/jobs/{jid}/versions?kind={kind}")
        ).json()["items"]
        assert len(items) == 1 and items[0]["detached"] is True
        assert await app.state.storage.get(
            f"versions/{jid}/{kind}/1"
        ) == expect
    assert not await app.state.storage.exists(f"exports/{jid}/md-layout")

async def test_auto_gen_snapshots_previous_md_layout(
    auth_client, app, done_job_with_result, db_session, monkeypatch
):
    """P1-3: LLM overwrite snapshots previous artifact (auto-gen/retry-layout)."""
    from app.core.models import Job
    from app.routers import exports

    jid = done_job_with_result
    st = app.state.storage
    await st.put(f"exports/{jid}/md-layout", b"# ban cu")

    async def fake_md(job_id, job, ir_sink=None, storage=None):
        return b"# ban moi"

    async def fake_docx(job_id, job, ir_sink=None):
        return b"docx bytes"

    monkeypatch.setattr(exports, "_llm_md_export", fake_md)
    monkeypatch.setattr(exports, "_llm_docx_export", fake_docx)
    job = await db_session.get(Job, jid)
    assert await exports.auto_generate_output(job, st) is True
    # P0-A: put dedupes → delete_prefix trước put → artifact = bytes mới;
    # bản cũ được snapshot xuống version history TRƯỚC khi ghi đè
    assert await st.get(f"exports/{jid}/md-layout") == b"# ban moi"
    items = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    ).json()["items"]
    assert [i["version"] for i in items] == [1]  # pre-overwrite snapshot
    assert await st.get(f"versions/{jid}/md-layout/1") == b"# ban cu"

async def test_auto_gen_snapshots_previous_docx_layout(
    auth_client, app, done_job_with_result, db_session, monkeypatch
):
    """P2-4: auto-gen snapshot docx-layout TRƯỚC overwrite (giống md-layout)
    — bản cũ phải còn trong version history sau lần auto-gen thứ 2."""
    from app.core.models import Job
    from app.routers import exports

    jid = done_job_with_result
    st = app.state.storage
    await st.put(f"exports/{jid}/docx-layout", b"docx ban cu")

    async def fake_md(job_id, job, ir_sink=None, storage=None):
        return b"# ban moi"

    async def fake_docx(job_id, job, ir_sink=None):
        return b"docx ban moi"

    monkeypatch.setattr(exports, "_llm_md_export", fake_md)
    monkeypatch.setattr(exports, "_llm_docx_export", fake_docx)
    job = await db_session.get(Job, jid)
    assert await exports.auto_generate_output(job, st) is True
    assert await st.get(f"exports/{jid}/docx-layout") == b"docx ban moi"
    items = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=docx-layout")
    ).json()["items"]
    assert [i["version"] for i in items] == [1]  # pre-overwrite snapshot
    assert await st.get(f"versions/{jid}/docx-layout/1") == b"docx ban cu"

async def test_auto_gen_overwrites_stale_artifacts(
    app, done_job_with_result, db_session, monkeypatch
):
    """P0-A: S3Driver.put dedupes → delete_prefix TRƯỚC put → retry-layout
   /auto-gen ghi đè artifact cũ (md-layout + docx-layout)."""
    from app.core.models import Job
    from app.routers import exports

    jid = done_job_with_result
    st = app.state.storage
    await st.put(f"exports/{jid}/md-layout", b"# ban cu")
    await st.put(f"exports/{jid}/docx-layout", b"docx ban cu")

    async def fake_md(job_id, job, ir_sink=None, storage=None):
        return b"# ban moi"

    async def fake_docx(job_id, job, ir_sink=None):
        return b"docx ban moi"

    monkeypatch.setattr(exports, "_llm_md_export", fake_md)
    monkeypatch.setattr(exports, "_llm_docx_export", fake_docx)
    job = await db_session.get(Job, jid)
    assert await exports.auto_generate_output(job, st) is True
    assert await st.get(f"exports/{jid}/md-layout") == b"# ban moi"
    assert await st.get(f"exports/{jid}/docx-layout") == b"docx ban moi"

async def test_restore_layout_snapshots_pre_overwrite(
    auth_client, app, done_job_with_result
):
    """P2: current artifact snapshotted before restore overwrite (crash-safe)."""
    jid = done_job_with_result
    st = app.state.storage
    await _seed_layouts(app, jid)
    await auth_client.get(f"/api/jobs/{jid}/extraction")  # lazy-seed v1
    # artifact drifts WITHOUT its own version (crash/legacy state);
    # put dedupes → delete first to simulate the drift
    await st.delete_prefix(f"exports/{jid}/md-layout")
    await st.put(f"exports/{jid}/md-layout", b"# loi khong co version")
    v1 = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    ).json()["items"][0]
    r = await auth_client.post(
        f"/api/jobs/{jid}/versions/{v1['id']}/restore"
    )
    assert r.status_code == 204, r.text
    assert await st.get(f"exports/{jid}/md-layout") == b"# Tieu de\n\nXin chao the gioi"
    assert await st.get(f"versions/{jid}/md-layout/2") == b"# loi khong co version"
    items = (
        await auth_client.get(f"/api/jobs/{jid}/versions?kind=md-layout")
    ).json()["items"]
    assert [i["version"] for i in items] == [3, 2, 1]

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

async def test_restore_docx_layout_binary_writes_layout_key(
    auth_client, app, done_job_with_result, db_session
):
    """P2: version kind docx-layout lưu BINARY render (P2-4 fallback
    snapshot) → restore ghi DOCX_LAYOUT_KEY; KHÔNG đè docx.html
    (GET docx.html .decode("utf-8") sẽ 500 với binary)."""
    jid = done_job_with_result
    st = app.state.storage
    await _seed_layouts(app, jid)
    binary = b"PK\x03\x04binary-render"
    v = await save_version(
        st, jid, "docx-layout", binary, 0, session=db_session
    )
    r = await auth_client.post(f"/api/jobs/{jid}/versions/{v.id}/restore")
    assert r.status_code == 204, r.text
    assert await st.get(f"exports/{jid}/docx-layout") == binary
    # docx.html giữ nguyên (không bị binary ghi đè / xóa)
    assert await st.get(f"exports/{jid}/docx.html") == \
        b"<p>Xin chao <b>the gioi</b></p>"
    dl = await auth_client.get(f"/api/jobs/{jid}/export/docx.html/download")
    assert dl.status_code == 200, dl.text


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

# --- audit-P1 verification (đóng bởi P0 stale badge; bổ sung test evidence) ---

async def test_audit_text_only_save_shows_stale_badge(auth_client, app, done_job_with_result):
    """Audit P1 (a): text-only save (KHÔNG old/new phrase) bump version →
    GET job stale_layouts hiện badge (sync skipped → layout rows behind)."""
    jid = done_job_with_result
    await _seed_layouts(app, jid)
    r = await auth_client.get(f"/api/jobs/{jid}/extraction")  # lazy-seed @tv0
    assert r.status_code == 200
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "Xin chao ban", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text_version"] == 1
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["text_version"] == 1
    assert body["stale_layouts"] == ["md", "docx"]

async def test_audit_restore_text_shows_badge_then_resync_clears(
    auth_client, app, done_job_with_result
):
    """Audit P1 (b): restore text version → stale badge hiện; extraction POST
    phrase resync → based_on bắt kịp → badge clear."""
    jid = done_job_with_result
    st = app.state.storage
    await _seed_layouts(app, jid)
    await auth_client.get(f"/api/jobs/{jid}/extraction")  # seed text v1 @tv0
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "Xin chao the gioi moi",
            "old_phrase": "the gioi",
            "new_phrase": "the gioi moi",
            "expected_text_version": 0,
        },
    )
    assert r.json()["synced"] == {"md": True, "docx": True}
    assert b"the gioi moi" in await st.get(f"exports/{jid}/md-layout")
    assert (await auth_client.get(f"/api/jobs/{jid}")).json()["stale_layouts"] == []
    # restore text v1 → tv 2 → badge hiện md+docx
    v1 = [
        i for i in (
            await auth_client.get(f"/api/jobs/{jid}/versions?kind=text")
        ).json()["items"]
        if i["version"] == 1
    ][0]
    r = await auth_client.post(f"/api/jobs/{jid}/versions/{v1['id']}/restore")
    assert r.status_code == 204, r.text
    body = (await auth_client.get(f"/api/jobs/{jid}")).json()
    assert body["text_version"] == 2
    assert body["stale_layouts"] == ["md", "docx"]
    # resync: phrase round-trip → layouts saved @tv3 → badge clear
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "Xin chào\n",
            "old_phrase": "the gioi moi",
            "new_phrase": "the gioi",
            "expected_text_version": 2,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == {"md": True, "docx": True}
    assert (await auth_client.get(f"/api/jobs/{jid}")).json()["stale_layouts"] == []


# --- WS-SERVER queue: save khi rendering + rerender flag + finalize guard ---

async def _rendering_job(db_session, VALID_RESULT_JSONB, mode: str | None = None) -> int:
    from sqlalchemy import select

    from app.core.models import Job, User

    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    job = Job(
        user_id=user.id,
        status="rendering",
        result=VALID_RESULT_JSONB,
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    if mode is not None:
        job.mode = mode
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

async def test_get_extraction_while_rendering_200(auth_client, db_session, VALID_RESULT_JSONB):
    """WS-UI: section Văn bản đọc GET /extraction khi status == rendering."""
    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    r = await auth_client.get(f"/api/jobs/{jid}/extraction")
    assert r.status_code == 200, r.text
    assert r.json()["text_version"] == 0

async def test_post_extraction_while_rendering_200_sets_rerender_flag(
    auth_client, db_session, VALID_RESULT_JSONB
):
    from app.core.models import Job

    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "van ban moi", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["requires_rerender"] is True
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.rerender_requested is True

async def test_post_extraction_extract_only_never_sets_rerender_flag(
    auth_client, db_session, VALID_RESULT_JSONB
):
    from app.core.models import Job

    jid = await _rendering_job(db_session, VALID_RESULT_JSONB, mode="extract_only")
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={"text": "van ban moi", "expected_text_version": 0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["requires_rerender"] is False
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.rerender_requested is False

async def test_post_extraction_sync_targeted_fail_sets_rerender_flag(
    auth_client, app, db_session, done_job_with_result
):
    """Done + layout artifact + sync targeted-fail → flag + requires_rerender."""
    from app.core.models import Job

    jid = done_job_with_result
    await app.state.storage.put(f"exports/{jid}/md-layout", b"# Tieu de")
    await app.state.storage.put(f"exports/{jid}/docx.html", b"<p>doc dac biet</p>")
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "dac biet",
            "old_phrase": "khong ton tai",
            "new_phrase": "x",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["requires_rerender"] is True
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.rerender_requested is True

async def test_auto_output_claim_pending_flag_single_render(
    auth_client, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """Flag có sẵn trước khi render → claim (clear) → render đúng 1 lần."""
    from sqlalchemy import update

    from app.core.models import Job
    from app.services import job_results

    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    await db_session.execute(
        update(Job).where(Job.id == jid).values(rerender_requested=True)
    )
    await db_session.commit()
    calls: list[int] = []

    async def _gen(job, storage):
        calls.append(1)
        return True

    monkeypatch.setattr("app.routers.exports.auto_generate_output", _gen)
    job = await db_session.get(Job, jid)
    await db_session.refresh(job)
    await job_results._auto_output(job, None)
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "done"
    assert calls == [1]
    assert job.rerender_requested is False

async def test_auto_output_rerenders_once_then_guard_keeps_flag(
    auth_client, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """Save trong lúc render → render lại tối đa 1 lần (guard 2); quá 2 → giữ cờ."""
    from sqlalchemy import update

    from app.core.models import Job
    from app.services import job_results

    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    calls: list[int] = []

    async def _gen(job, storage):
        calls.append(1)
        # user save ngay trong lúc render → cờ lại bật
        await db_session.execute(
            update(Job).where(Job.id == jid).values(rerender_requested=True)
        )
        await db_session.commit()
        return True

    monkeypatch.setattr("app.routers.exports.auto_generate_output", _gen)
    job = await db_session.get(Job, jid)
    await db_session.refresh(job)
    await job_results._auto_output(job, None)
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "done"
    assert len(calls) == 2  # guard 2 — không render lần 3
    assert job.rerender_requested is True  # quá 2 → giữ cờ + log warning

async def test_auto_output_pass2_reloads_result_saved_between_passes(
    auth_client, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """P1-1: user save GIỮA pass 1 và pass 2 → pass 2 phải render text MỚI."""
    from sqlalchemy import update

    from app.core.models import Job
    from app.services import job_results

    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    await db_session.execute(
        update(Job).where(Job.id == jid).values(rerender_requested=True)
    )
    await db_session.commit()
    seen: list[str | None] = []

    async def _gen(job, storage):
        seen.append((job.result or {}).get("extraction_text"))
        if len(seen) == 1:
            # user save NGAY trong lúc pass 1 render → result mới + cờ vẽ lại.
            # Session RIÊNG (như POST /extraction thật) — không đụng object `job`.
            from app.core.db import SessionLocal

            async with SessionLocal() as save_session:
                await save_session.execute(
                    update(Job)
                    .where(Job.id == jid)
                    .values(
                        result={
                            **(job.result or {}),
                            "extraction_text": "van ban moi",
                        },
                        rerender_requested=True,
                    )
                )
                await save_session.commit()
        return True

    monkeypatch.setattr("app.routers.exports.auto_generate_output", _gen)
    job = await db_session.get(Job, jid)
    await db_session.refresh(job)
    await job_results._auto_output(job, None)
    assert len(seen) == 2  # cờ giữa chừng → render thêm 1 pass
    assert seen[1] == "van ban moi"  # stale job object → pass 2 render text cũ

async def test_post_extraction_rendering_flag_only_skips_sync(
    auth_client, app, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """P2-4: save khi rendering → KHÔNG sync (artifact đang bị render task ghi)."""
    jid = await _rendering_job(db_session, VALID_RESULT_JSONB)
    await _seed_layouts(app, jid)
    calls: list[int] = []

    async def _sync(*args, **kwargs):
        calls.append(1)
        return {"md": True, "docx": True}

    monkeypatch.setattr("app.routers.jobs.sync_job_layouts", _sync)
    r = await auth_client.post(
        f"/api/jobs/{jid}/extraction",
        json={
            "text": "van ban moi",
            "old_phrase": "Xin chao",
            "new_phrase": "Xin chao moi",
            "expected_text_version": 0,
        },
    )
    assert r.status_code == 200, r.text
    assert calls == []  # RED: read-modify-write trên artifact đang render
    assert r.json()["requires_rerender"] is True  # flag-only — render pass sau vẽ lại
