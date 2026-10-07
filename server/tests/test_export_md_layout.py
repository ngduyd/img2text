"""Plan D5: md-layout export via LLM (services/llm_md) + auto-gen md.

No live LLM: httpx.AsyncClient is monkeypatched to canned responses.
Covers: happy path (storage key + download Content-Type), content-verbatim
validation → 502 exact + NO cache, HTML table → md table '|', geometry
indent → TAB prefix, LLM ConnectError → 502 exact, response_format retry,
auto-gen md = md-layout on success / plain-md fallback + warning on
failure, missing result 409, other-user 403.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, User
from app.services import llm_md
from app.services.llm_md import LLMMdContentError, LLMMdError, build_md

from tests.test_export_llm_docx import FakeResponse  # canned LLM responses
from tests.test_jobs_read import other_client  # noqa: F401

MD_CONTENT_TYPE = "text/markdown; charset=utf-8"

# Verbatim sources for VALID_RESULT_JSONB (conftest): r0 text + empty r1 skipped
GOOD_MD = "# Xin chào"

def fake_llm(monkeypatch, responses: list) -> list:
    """Patch httpx.AsyncClient as llm_md sees it; returns recorded calls.

    `responses` items: FakeResponse → returned, Exception → raised.
    """
    calls: list = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, dict(json or {}), dict(headers or {})))  # copy
            resp = responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp

    monkeypatch.setattr(llm_md.httpx, "AsyncClient", Client)
    return calls

def _md_response(markdown: str) -> FakeResponse:
    return FakeResponse(json.dumps({"markdown": markdown}))

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
TABLE_MD = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nchú thích"

# geometry fixture: two stacked blocks with the SAME xmin/xmax
GEOM_RESULT = _result([
    _region("r0", [10, 20, 390, 60], "cột trái"),
    _region("r1", [10, 80, 390, 120], "cột phải"),
])
GEOM_MD = "cột trái\n\n\tcột phải"  # LLM indents the second block with TAB

# --- build_md unit ---

async def test_build_md_happy(monkeypatch, VALID_RESULT_JSONB, caplog):
    caplog.set_level("INFO", logger="app.services.llm_md")
    calls = fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    assert await build_md(VALID_RESULT_JSONB) == GOOD_MD
    url, payload, _ = calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == settings.llm_model
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][0]["content"]
    assert '"Xin chào"' in prompt  # verbatim text in input
    assert '"bbox"' in prompt  # geometry for the indent rule
    # observability: one INFO "llm called" line per POST (no prompt logged)
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any(m.startswith("llm called: fmt=md-layout") for m in info), info
    assert not any(GOOD_MD in m for m in info)  # never log prompt/content

async def test_build_md_table_block_keeps_md_table(monkeypatch):
    """Rule 1: type=table → real md table '| ... |' passes validation."""
    fake_llm(monkeypatch, [_md_response(TABLE_MD)])
    out = await build_md(TABLE_RESULT)
    assert "| A | B |" in out and "| 1 | 2 |" in out

async def test_build_md_same_bbox_gets_tab_indent(monkeypatch):
    """Rule 2: same xmin/xmax → LLM's TAB indent passes validation."""
    fake_llm(monkeypatch, [_md_response(GEOM_MD)])
    out = await build_md(GEOM_RESULT)
    assert out.splitlines()[2].startswith("\t")  # right block indented

async def test_build_md_heading_and_emphasis_pass(monkeypatch):
    fake_llm(monkeypatch, [_md_response("# Xin chào")])
    assert await build_md(_result([_region("r0", [1, 2, 3, 4], "Xin chào")])) == "# Xin chào"

async def test_build_md_midline_emphasis_passes(monkeypatch):
    """D5 review P1: mid-line ** must not trip verbatim validation."""
    result = _result([_region("r0", [1, 2, 3, 4], "giá trị quan trọng")])
    fake_llm(monkeypatch, [_md_response("giá trị **quan trọng**")])
    assert await build_md(result) == "giá trị **quan trọng**"

async def test_build_md_word_emphasis_passes(monkeypatch):
    result = _result([_region("r0", [1, 2, 3, 4], "Xin chào")])
    fake_llm(monkeypatch, [_md_response("Xin **chào**")])
    assert await build_md(result) == "Xin **chào**"

async def test_build_md_table_cell_escaped_pipe_passes(monkeypatch):
    r"""D5 review P1: escaped pipe in a table cell (a\|b) = source a|b."""
    result = _result([
        _region("r0", [1, 2, 798, 40], "<table><tr><td>a|b</td></tr></table>")
    ])
    md = "| a\\|b |"
    fake_llm(monkeypatch, [_md_response(md)])
    assert await build_md(result) == md

async def test_build_md_content_modified_raises(monkeypatch, VALID_RESULT_JSONB):
    fake_llm(monkeypatch, [_md_response("# Xin chao da sua")])
    with pytest.raises(LLMMdContentError):
        await build_md(VALID_RESULT_JSONB)

async def test_build_md_llm_down_raises(monkeypatch, VALID_RESULT_JSONB, caplog):
    caplog.set_level("INFO", logger="app.services.llm_md")
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    with pytest.raises(LLMMdError):
        await build_md(VALID_RESULT_JSONB)
    # failed calls stay observable: INFO "llm called" + WARNING
    assert any(
        r.getMessage().startswith("llm called: fmt=md-layout")
        for r in caplog.records
    )
    assert any(r.levelname == "WARNING" for r in caplog.records)

async def test_build_md_retries_without_response_format(
    monkeypatch, VALID_RESULT_JSONB
):
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            _md_response(GOOD_MD),
        ],
    )
    assert await build_md(VALID_RESULT_JSONB) == GOOD_MD
    assert "response_format" in calls[0][1]
    assert "response_format" not in calls[1][1]

async def test_build_md_bearer_header_key_set(monkeypatch, VALID_RESULT_JSONB, caplog):
    """Key set → Authorization: Bearer on BOTH attempts (incl. bare retry);
    key never in logs."""
    caplog.set_level("INFO", logger="app.services.llm_md")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-2")
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            _md_response(GOOD_MD),
        ],
    )
    assert await build_md(VALID_RESULT_JSONB) == GOOD_MD
    assert [c[2] for c in calls] == [
        {"Authorization": "Bearer sk-test-2"},
        {"Authorization": "Bearer sk-test-2"},
    ]
    assert not any("sk-test-2" in r.getMessage() for r in caplog.records)

async def test_build_md_no_auth_header_key_empty(monkeypatch, VALID_RESULT_JSONB):
    """Empty key → no Authorization header (local server, no auth)."""
    monkeypatch.setattr(settings, "llm_api_key", "")
    calls = fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    assert await build_md(VALID_RESULT_JSONB) == GOOD_MD
    assert "Authorization" not in calls[0][2]

# --- export route ---

async def test_export_md_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["url"]
    body = await storage.get(f"exports/{done_job_with_result}/md-layout")
    assert body.decode("utf-8") == GOOD_MD

async def test_export_md_layout_download_content_type(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 200, r.text
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/md-layout/download"
    )
    assert r.status_code == 200
    assert r.content.decode("utf-8") == GOOD_MD
    assert r.headers["content-type"] == MD_CONTENT_TYPE

async def test_export_md_layout_content_modified_502_no_cache(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [_md_response("# nội dung đã bị sửa")])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 502
    assert r.json()["detail"] == "LLM sửa nội dung — thử lại."
    assert not await storage.exists(f"exports/{done_job_with_result}/md-layout")

async def test_export_md_layout_llm_down_502_no_cache(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 502
    assert r.json()["detail"] == "Không kết nối LLM máy chủ."
    assert not await storage.exists(f"exports/{done_job_with_result}/md-layout")

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
    fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    r = await other_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "md-layout"}
    )
    assert r.status_code == 403

# --- auto-gen (job_results → auto_generate_output) ---

async def test_auto_md_llm_ok_stores_md_layout(
    worker_client, seed_job, storage_spy, db_session, VALID_RESULT_JSONB, monkeypatch
):
    """D5: output_format=md auto-gen writes the LLM md-layout to exports/{id}/md."""
    from app.services.job_results import drain_auto_output

    fake_llm(monkeypatch, [_md_response(GOOD_MD)])
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    data = await storage_spy.get(f"exports/{seed_job}/md")
    assert data.decode("utf-8") == GOOD_MD  # md-layout, not plain result md
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
    """D5: LLM failure → warning + fallback (exports/{id}/md still written)."""
    from app.services.job_results import drain_auto_output

    def _down(*args, **kwargs):
        raise LLMMdError("LLM down (test)")

    monkeypatch.setattr("app.routers.exports.build_md", _down)
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
    assert data.decode("utf-8") == VALID_RESULT_JSONB["markdown"]  # plain-md fallback
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"
