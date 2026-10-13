"""md-layout export via LLM IR (services/render_md) + auto-gen md.

No live LLM: httpx.AsyncClient is monkeypatched to canned responses.
Covers: happy path (storage key + download Content-Type), geometry indent,
HTML table → md table, LLM IR (heading/paragraph), LLM ConnectError → fallback,
auto-gen md = md-layout on success / plain-md fallback on failure,
missing result 409, other-user 403.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, User
from app.services.render_md import LLMError, build_md

from tests.test_export_llm_docx import FakeResponse  # canned LLM responses
from tests.test_jobs_read import other_client  # noqa: F401

MD_CONTENT_TYPE = "text/markdown; charset=utf-8"

GOOD_MD = "# Xin chào"


def fake_llm(monkeypatch, responses: list) -> list:
    """Patch httpx.AsyncClient as render_md sees it; returns recorded calls."""
    calls: list = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, dict(json or {}), dict(headers or {})))
            resp = responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return calls


def _ir_response() -> FakeResponse:
    return FakeResponse(json.dumps({
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [{
            "page_id": "page_001",
            "page_number": 1,
            "header": [],
            "content": [
                {
                    "id": "node_001",
                    "type": "heading",
                    "role": "section_heading",
                    "text": "Xin chào",
                    "align": "left",
                    "indent": 0,
                    "source_block_ids": ["r0"],
                    "children": [],
                }
            ],
            "footer": [],
        }],
    }))


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

async def test_build_md_happy(monkeypatch, VALID_RESULT_JSONB, caplog):
    caplog.set_level("INFO", logger="render_md")
    calls = fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
    out = await build_md(VALID_RESULT_JSONB)
    assert "Xin chào" in out
    url, payload, _ = calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == settings.ir_llm_model
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][0]["content"]
    assert '"Xin chào"' in prompt
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any(m.startswith("llm called: model=") for m in info), info
    assert not any(GOOD_MD in m for m in info)


async def test_build_md_table_block_keeps_md_table(monkeypatch):
    """HTML table → real md table '| ... |'."""
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
    out = await build_md(TABLE_RESULT)
    # IR response has heading "Xin chào" but table is in OCR — fallback handles it
    # Actually with use_llm=True and valid IR, it renders from IR
    # The IR response above doesn't include table, so this tests fallback
    # Let me use use_llm=False for pure heuristic
    out = await build_md(TABLE_RESULT, use_llm=False)
    assert "| A | B |" in out and "| 1 | 2 |" in out


async def test_build_md_same_bbox_gets_tab_indent(monkeypatch):
    """Block thụt lề (x0 > margin) → TAB prefix."""
    result = _result([
        _region("r0", [10, 20, 390, 60], "lề trái"),
        _region("r1", [100, 80, 390, 120], "thụt vào"),
    ])
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
    out = await build_md(result, use_llm=False)
    lines = out.splitlines()
    assert any(l.startswith("\t") for l in lines)


async def test_build_md_heading_from_ir(monkeypatch):
    """IR heading → '## ' prefix (section_heading = level 2)."""
    result = _result([_region("r0", [1, 2, 3, 4], "Xin chào")])
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("## Xin chào")])
    out = await build_md(result)
    assert out.startswith("## ")


async def test_build_md_llm_down_warns_not_raises(monkeypatch, VALID_RESULT_JSONB, caplog):
    """LLM down → warning + heuristic fallback (no raise)."""
    caplog.set_level("WARNING", logger="render_md")
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    out = await build_md(VALID_RESULT_JSONB)
    assert out
    assert any("HEURISTIC FALLBACK" in r.getMessage() for r in caplog.records)


async def test_build_md_retries_without_response_format(
    monkeypatch, VALID_RESULT_JSONB
):
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            _ir_response(),
            FakeResponse("## Xin chào"),
        ],
    )
    await build_md(VALID_RESULT_JSONB)
    assert "response_format" in calls[0][1]
    assert "response_format" not in calls[1][1]


async def test_build_md_bearer_header_key_set(monkeypatch, VALID_RESULT_JSONB, caplog):
    """Key set → Authorization: Bearer on BOTH attempts; key never in logs."""
    caplog.set_level("INFO", logger="app.services.render_md")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-2")
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            _ir_response(),
            FakeResponse("## Xin chào"),
        ],
    )
    await build_md(VALID_RESULT_JSONB)
    assert all(
        c[2] == {"Authorization": "Bearer sk-test-2"} for c in calls
    )
    assert not any("sk-test-2" in r.getMessage() for r in caplog.records)


async def test_build_md_no_auth_header_key_empty(monkeypatch, VALID_RESULT_JSONB):
    """Empty key → no Authorization header."""
    monkeypatch.setattr(settings, "llm_api_key", "")
    calls = fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
    await build_md(VALID_RESULT_JSONB)
    assert "Authorization" not in calls[0][2]


# --- export route ---

async def test_export_md_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
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
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
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
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
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
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
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
        from app.services.render_docx import LLMError as DocxLLMError
        raise DocxLLMError("LLM down (test)")

    monkeypatch.setattr("app.routers.exports.build_docx", _docx_down)
    fake_llm(monkeypatch, [_ir_response(), FakeResponse("# Xin chào")])
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
        raise LLMError("LLM down (test)")

    async def _docx_down(*args, **kwargs):
        from app.services.render_docx import LLMError as DocxLLMError
        raise DocxLLMError("LLM down (test)")

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
    import importlib
    result = _result([
        _region("r0", [1, 2, 30, 40], "Nội dung"),
        {"id": "r1", "bbox": [5, 6, 70, 80], "text": "",
         "verdict": "image_unextractable", "placeholder": True},
    ])
    for modname in ("app.services.render_md", "app.services.render_docx"):
        mod = importlib.import_module(modname)
        blocks = mod.extract_pages(result)[0].blocks
        assert any(b.kind == "image" for b in blocks), modname

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
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
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

    rid = "p1_b3"
    marker = IMAGE_MARKER.format(region_id=rid)
    await storage_spy.put(f"exports/{done_job_with_result}/crops/{rid}.png", b"\x89PNG\r\n\x1a\nx")
    fake_llm(monkeypatch, [_ir_response(), FakeResponse(f"# X\n\n{marker}")])
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

# --- Wave-4 #8: coverage fail → giữ heuristic render + ir_json cũ (không stub) ---

async def test_auto_gen_coverage_fail_keeps_heuristic_and_old_ir(
    app, done_job_with_result, db_session, monkeypatch
):
    """COVERAGE fail cả2 build → md-layout = heuristic content (KHÔNG stub
    0 blocks 'xóa đầu ra'); job.ir_json GIỮ giá trị cũ (không overwrite)."""
    from app.routers import exports

    jid = done_job_with_result
    st = app.state.storage
    job = await db_session.get(Job, jid)
    job.ir_json = '{"document_id": "old", "schema_version": "1.0", "pages": []}'
    await db_session.commit()

    # IR thiếu r1 (image exempt) + r0? cover r0 only → thiếu... VALID có r0 text
    # + r1 image. LLM cover r0 → coverage OK; để FAIL phải bỏ r0:
    bad_ir = {
        "document_id": "doc_001", "schema_version": "1.0",
        "pages": [{
            "page_id": "p1", "page_number": 1, "header": [], "content": [],
            "footer": [],
        }],
    }
    fake_llm(monkeypatch, [
        FakeResponse(json.dumps(bad_ir)), FakeResponse("# nope"),
        FakeResponse(json.dumps(bad_ir)), FakeResponse("<p>nope</p>"),
    ])
    assert await exports.auto_generate_output(job, st) is True
    # md-layout có nội dung heuristic từ OCR (r0 "Xin chào"), không rỗng/stub
    md = (await st.get(f"exports/{jid}/md-layout")).decode()
    assert "Xin chào" in md
    # ir_json giữ nguyên cũ — stub 0-block không ghi đè
    await db_session.refresh(job)
    assert json.loads(job.ir_json)["document_id"] == "old"
