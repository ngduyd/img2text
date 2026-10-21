"""md-layout export via layout_spec (services/render_md, 0 LLM) + auto-gen md.

Covers: happy path (storage key + download Content-Type), geometry indent,
HTML table → md table, auto-gen md = md-layout on success / plain-md fallback
on failure, missing result 409, other-user 403, crop embed (relative key /
on-demand data-URI).
"""

import json

import pytest
from sqlalchemy import select

from app.core.models import Job, User
from app.services.render_md import build_md

from tests.test_jobs_read import other_client  # noqa: F401

MD_CONTENT_TYPE = "text/markdown; charset=utf-8"

GOOD_MD = "# Xin chào"


def _result(regions: list[dict]) -> dict:
    return {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 0.0,
        "warnings": [],
        "markdown": "",
        "pages": [
            {"index": 0, "width": 800, "height": 600, "page_flag": "ok",
             "markdown": "", "regions": regions}
        ],
    }


def _region(rid: str, bbox: list, text: str) -> dict:
    return {"id": rid, "bbox": bbox, "text": text, "verdict": "ok",
            "placeholder": False}


TABLE_RESULT = _result([
    _region("r0", [1, 2, 798, 40],
            "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"),
    _region("r1", [1, 60, 798, 100], "chú thích"),
])

GEOM_RESULT = _result([
    _region("r0", [10, 20, 390, 60], "cột trái"),
    _region("r1", [10, 80, 390, 120], "cột phải"),
])


# --- build_md unit ---

async def test_build_md_uses_spec_no_llm():
    """build_md không gọi LLM: bảng HTML trong OCR → md table (spec path)."""
    out = await build_md(TABLE_RESULT)
    assert "| A | B |" in out and "| 1 | 2 |" in out

async def test_build_md_same_bbox_gets_space_indent():
    """Block thụt lề (x0 > margin) → prefix SPACE (phase 1: bỏ tab thô)."""
    result = _result([
        _region("r0", [10, 20, 390, 60], "lề trái"),
        _region("r1", [100, 80, 390, 120], "thụt vào"),
    ])
    out = await build_md(result)
    lines = out.splitlines()
    assert any(l.startswith(" ") for l in lines)
    assert not any(l.startswith("\t") for l in lines)

# --- export route ---

async def test_export_md_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["url"]
    body = await storage.get(f"exports/{done_job_with_result}/md-layout")
    assert body


async def test_export_md_layout_download_content_type(
    auth_client, done_job_with_result, storage, monkeypatch
):
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/md-layout/download"
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == MD_CONTENT_TYPE


async def test_export_md_layout_llm_down_falls_back(
    auth_client, done_job_with_result, storage, monkeypatch
):
    """LLM down → heuristic fallback (no 502, file still written)."""
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200
    assert await storage.exists(f"exports/{done_job_with_result}/md-layout")


async def test_export_md_layout_missing_result_409(auth_client, db_session):
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=None,
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    r = await auth_client.post(
        f"/api/jobs/{job.id}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Chưa có kết quả OCR."


async def test_export_md_layout_other_user_403(
    auth_client, other_client, done_job_with_result, monkeypatch
):
    r = await other_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 403


# --- auto-gen (job_results → auto_generate_output) ---

async def test_auto_md_llm_ok_stores_md_layout(
    worker_client, seed_job, storage_spy, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """output_format=md auto-gen writes md-layout to exports/{id}/md-layout."""
    from app.services.job_results import drain_auto_output

    async def _docx_down(*args, **kwargs):
        raise RuntimeError("render down (test)")

    monkeypatch.setattr("app.routers.exports.build_docx", _docx_down)
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    data = await storage_spy.get(f"exports/{seed_job}/md-layout")
    assert data
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"


async def test_auto_md_llm_down_falls_back_to_plain_md(
    worker_client,
    seed_job,
    storage_spy,
    db_session,
    VALID_RESULT_JSONB,
    monkeypatch,
    caplog,
):
    """LLM failure → warning + fallback (exports/{id}/md still written);
    BOTH layouts failed → spec 2026-10-09: failed + failed_step="rendering"."""
    from app.services.job_results import drain_auto_output

    def _down(*args, **kwargs):
        raise RuntimeError("render down (test)")

    async def _docx_down(*args, **kwargs):
        raise RuntimeError("render down (test)")

    monkeypatch.setattr("app.routers.exports.build_md", _down)
    monkeypatch.setattr("app.routers.exports.build_docx", _docx_down)
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    with caplog.at_level("WARNING", logger="app.services.job_results"):
        r = await worker_client.post(
            f"/api/jobs/{seed_job}/result",
            json=VALID_RESULT_JSONB,
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        await drain_auto_output()
    assert any("fallback" in rec.getMessage() for rec in caplog.records)
    data = await storage_spy.get(f"exports/{seed_job}/md")
    assert data.decode("utf-8") == VALID_RESULT_JSONB["markdown"]
    job = await db_session.get(Job, seed_job)
    assert job.status == "failed" and job.failed_step == "rendering"

# --- P1-R4a/R5: image region sống sót qua heuristic ---

def test_heuristic_extract_keeps_empty_image_block():
    """P1-R4a: image region text rỗng → node image KHÔNG bị drop
    (cả 2 renderer: render_md + render_docx)."""
    result = _result([
        _region("r0", [1, 2, 30, 40], "Nội dung"),
        {"id": "r1", "bbox": [5, 6, 70, 80], "text": "",
         "verdict": "image_unextractable", "placeholder": True},
    ])
    # render_docx giờ đi layout_spec (không còn extract_pages riêng);
    # pin: md block model + spec block model đều giữ block image.
    from app.services import layout_spec, render_md

    blocks = render_md.extract_pages(result)[0].blocks
    assert any(b.kind == "image" for b in blocks), "render_md"
    spec_blocks = layout_spec.build_page_specs(result)[0].blocks
    assert any(b.kind == "image" for b in spec_blocks), "layout_spec"

async def test_export_md_layout_fallback_keeps_image_marker(
    auth_client, db_session, storage, monkeypatch
):
    """P1-R5: adapt_batch doc có image rỗng → export md-layout LLM-down
    → marker ảnh sống trong md fallback (không crash, không mất ảnh)."""
    from app.services.kaggle_orchestrator import adapt_batch_document
    from tests.test_region_edit import _seed_done
    doc = {"pages": [{"page": 1, "width": 800, "height": 600, "blocks": [
        {"id": "b0", "type": "text", "bbox": [10, 10, 400, 40],
         "text": "Nội dung"},
        {"id": "b1", "type": "image", "bbox": [10, 60, 400, 200],
         "text": ""},
    ]}]}
    job_id = await _seed_done(db_session, adapt_batch_document(doc))
    r = await auth_client.post(
        f"/api/jobs/{job_id}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    md = (await storage.get(f"exports/{job_id}/md-layout")).decode("utf-8")
    assert "Nội dung" in md
    assert "**[Hình ảnh chưa trích xuất: vùng b1]**" in md

# --- WS-PIPE P1: md-layout artifact không bake presigned URL (hết hạn 24h) ---

async def test_md_layout_artifact_relative_key_download_fresh_url(
    auth_client, done_job_with_result, storage_spy, monkeypatch
):
    from app.core.schemas import IMAGE_MARKER

    rid = "r1"  # VALID_RESULT_JSONB: image region → IMAGE_MARKER trong spec md
    assert IMAGE_MARKER.format(region_id=rid)
    await storage_spy.put(f"exports/{done_job_with_result}/crops/{rid}.png", b"\x89PNG\r\n\x1a\nx")
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    body = (await storage_spy.get(f"exports/{done_job_with_result}/md-layout")).decode()
    assert f"](crops/{rid}.png)" in body  # relative key trong artifact
    assert "http" not in body             # KHÔNG hostname presigned baked

    r1 = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/md-layout/download"
    )
    r2 = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/md-layout/download"
    )
    assert r1.status_code == 200
    for r_ in (r1, r2):
        assert f"crops/{rid}.png" in r_.text   # URL trỏ đúng key
        assert "http" in r_.text               # presigned fresh tại serve
    # presign GỌI MỖI lần serve (URL ký theo timestamp giây — spy chứng minh
    # fresh, không cache)
    n = storage_spy.presign_get.await_count
    assert n >= 2  # ≥1 call/serve

# --- auto-gen không còn sinh IR eager (job.ir_json do /ir on-demand) ---

async def test_auto_gen_keeps_old_ir(
    app, done_job_with_result, db_session, monkeypatch
):
    """auto-gen (md+docx) không ghi job.ir_json — IR sinh on-demand ở /ir."""
    from app.routers import exports

    jid = done_job_with_result
    st = app.state.storage
    job = await db_session.get(Job, jid)
    job.ir_json = '{"document_id": "old", "schema_version": "1.0", "pages": []}'
    await db_session.commit()

    assert await exports.auto_generate_output(job, st) is True
    # md-layout có nội dung spec từ OCR (r0 "Xin chào"), không rỗng
    md = (await st.get(f"exports/{jid}/md-layout")).decode()
    assert "Xin chào" in md
    # ir_json giữ nguyên cũ — auto-gen không sinh IR eager
    await db_session.refresh(job)
    assert json.loads(job.ir_json)["document_id"] == "old"

# --- Wave-4 #9: crop embed on-demand qua export route (marker → data-URI) ---

async def test_export_md_layout_ondemand_crop_embeds_data_uri(
    auth_client, app, done_job_with_result, db_session, monkeypatch
):
    """Crop artifact CHƯA ingest + original có trong S3 → on-demand crop
    (get_or_make_crop) → md-layout chứa data-URI (marker biến mất)."""
    import io

    from PIL import Image

    jid = done_job_with_result
    st = app.state.storage
    img = Image.new("RGB", (200, 400), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    await st.put("uploads/test.jpg", buf.getvalue())

    rid = "r1"  # VALID_RESULT_JSONB: verdict image_unextractable, bbox [5,6,70,80]
    from app.core.schemas import IMAGE_MARKER
    marker = IMAGE_MARKER.format(region_id=rid)
    r = await auth_client.post(
        f"/api/jobs/{jid}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    body = (await st.get(f"exports/{jid}/md-layout")).decode()
    assert marker not in body
    assert f"![vùng {rid}](data:image/jpeg;base64," in body
    assert "http" not in body  # không URL baked
    # crop on-demand được cache: crops/{jid}/{rid}.jpg (lần sau cache-hit)
    assert await st.exists(f"crops/{jid}/{rid}.jpg")

# --- Lane K: batch crop (kernel PNG) thắng on-demand tại route ---

async def test_export_md_layout_batch_crop_wins_relative_key(
    auth_client, app, done_job_with_result, monkeypatch
):
    """Crop kernel ĐÃ ingest exports/{jid}/crops/r1.png → md-layout chứa
    relative key crops/r1.png (KHÔNG data-URI); on-demand get_or_make_crop
    KHÔNG chạy (không sinh crops/{jid}/r1.jpg)."""
    jid = done_job_with_result
    st = app.state.storage
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
        "7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000"
        "0049454e44ae426082"
    )
    await st.put(f"exports/{jid}/crops/r1.png", png)

    r = await auth_client.post(
        f"/api/jobs/{jid}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    body = (await st.get(f"exports/{jid}/md-layout")).decode()
    assert "![vùng r1](crops/r1.png)" in body
    assert "data:image" not in body
    assert not await st.exists(f"crops/{jid}/r1.jpg")  # on-demand không chạy
