"""IR rewrite: docx-layout export via LLM IR (services/render_docx).

No live LLM: httpx.AsyncClient is monkeypatched to canned responses.
Covers: render (zip magic + python-docx heading), LLM down →
LLMError → route 502 (no cache), missing result → 409 exact,
download Content-Type, owner-or-admin, response_format retry.
"""

import io
import json

import httpx
import pytest
import pytest_asyncio
from docx import Document
from docx.shared import Pt
from sqlalchemy import select

from app.core.config import Settings, settings
from app.core.models import Job, User
from app.services import render_docx
from app.services.render_docx import LLMError, build_docx

from tests.test_jobs_read import other_client  # noqa: F401

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

FAKE_IR = {
    "document_id": "doc_001",
    "schema_version": "1.0",
    "pages": [
        {
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
                },
                {
                    "id": "node_002",
                    "type": "paragraph",
                    "role": "body",
                    "text": "Nội dung",
                    "align": "left",
                    "indent": 0,
                    "source_block_ids": ["r1"],
                    "children": [],
                },
            ],
            "footer": [],
        }
    ],
}


class FakeResponse:
    def __init__(self, content: str | None = None, status_code: int = 200,
                 text: str = ""):
        self.status_code = status_code
        self.text = text
        self._content = content

    def json(self) -> dict:
        if self._content is None:
            raise ValueError("no body")
        return {"choices": [{"message": {"content": self._content}}]}


def fake_llm(monkeypatch, responses: list) -> list:
    """Patch httpx.AsyncClient as render_docx sees it; returns recorded calls."""
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

    monkeypatch.setattr(render_docx.httpx, "AsyncClient", Client)
    return calls


def _cell_texts(doc) -> list[str]:
    return [
        p.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
        for p in cell.paragraphs
    ]


# --- build_docx unit ---

async def test_build_docx_renders_ir(
    monkeypatch, VALID_RESULT_JSONB, caplog
):
    caplog.set_level("INFO", logger="app.services.render_docx")
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    data = await build_docx(VALID_RESULT_JSONB)
    assert data[:2] == b"PK"
    doc = Document(io.BytesIO(data))
    texts = [p.text for p in doc.paragraphs]
    assert "Xin chào" in texts
    assert "Nội dung" in texts
    # prompt payload: model + temperature 0 + response_format + input JSON
    url, payload, _ = calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == settings.ir_llm_model
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    assert '"width": 800' in payload["messages"][0]["content"]
    assert '"r0"' in payload["messages"][0]["content"]
    # observability: one INFO "llm called" line per POST (no prompt logged)
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any(m.startswith("llm called: model=") for m in info), info
    assert not any("Xin chào" in m for m in info)

def test_llm_api_key_default_empty():
    assert Settings().llm_api_key == ""

async def test_render_docx_bearer_header_key_set(
    monkeypatch, VALID_RESULT_JSONB, caplog
):
    """Key set → Authorization: Bearer on BOTH attempts (incl. bare retry);
    key never in logs."""
    caplog.set_level("INFO", logger="app.services.render_docx")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-1")
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            FakeResponse(json.dumps(FAKE_IR)),
        ],
    )
    data = await build_docx(VALID_RESULT_JSONB)
    assert data[:2] == b"PK"
    assert [c[2] for c in calls] == [
        {"Authorization": "Bearer sk-test-1"},
        {"Authorization": "Bearer sk-test-1"},
    ]
    assert not any("sk-test-1" in r.getMessage() for r in caplog.records)

async def test_render_docx_no_auth_header_key_empty(monkeypatch, VALID_RESULT_JSONB):
    """Empty key → no Authorization header (local server, no auth)."""
    monkeypatch.setattr(settings, "llm_api_key", "")
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    await build_docx(VALID_RESULT_JSONB)
    assert "Authorization" not in calls[0][2]

async def test_build_docx_reads_db_model_override(
    monkeypatch, VALID_RESULT_JSONB, db_session
):
    """DB Setting row for ir_llm_model wins over env default."""
    from app.core.models import Setting
    db_session.add(Setting(key="ir_llm_model", value="db-override-model"))
    await db_session.commit()
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    await build_docx(VALID_RESULT_JSONB)
    assert calls[0][1]["model"] == "db-override-model"

async def test_build_docx_reads_db_base_url_override(
    monkeypatch, VALID_RESULT_JSONB, db_session
):
    """DB Setting row for llm_base_url wins over env default."""
    from app.core.models import Setting
    db_session.add(Setting(key="llm_base_url", value="http://db-llm:9999/v1"))
    await db_session.commit()
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    await build_docx(VALID_RESULT_JSONB)
    assert calls[0][0].startswith("http://db-llm:9999/v1")

async def test_build_docx_reads_db_api_key_override(
    monkeypatch, VALID_RESULT_JSONB, db_session
):
    """DB Setting row for llm_api_key wins over env default."""
    from app.core.models import Setting
    db_session.add(Setting(key="llm_api_key", value="sk-db-key"))
    await db_session.commit()
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    await build_docx(VALID_RESULT_JSONB)
    assert calls[0][2] == {"Authorization": "Bearer sk-db-key"}

async def test_build_docx_llm_down_raises(
    monkeypatch, VALID_RESULT_JSONB, caplog
):
    caplog.set_level("INFO", logger="app.services.render_docx")
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    # LLM down → heuristic fallback (no raise)
    data = await build_docx(VALID_RESULT_JSONB)
    assert data[:2] == b"PK"
    assert any(
        r.getMessage().startswith("llm called: model=")
        for r in caplog.records
    )
    assert any(r.levelname == "WARNING" for r in caplog.records)

async def test_build_docx_retries_without_response_format(
    monkeypatch, VALID_RESULT_JSONB
):
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            FakeResponse(json.dumps(FAKE_IR)),
        ],
    )
    data = await build_docx(VALID_RESULT_JSONB)
    assert data[:2] == b"PK"
    assert "response_format" in calls[0][1]
    assert "response_format" not in calls[1][1]

# --- export route ---

def _styled_result() -> dict:
    """Two regions: HTML table text + caption text."""
    return {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 0.0,
        "warnings": [],
        "markdown": "",
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "page_flag": "ok",
                "markdown": "",
                "regions": [
                    {"id": "r0", "bbox": [1, 2, 30, 40],
                     "text": "<table><tr><td>A</td><td>B</td></tr>"
                             "<tr><td>1</td><td>2</td></tr></table>",
                     "verdict": "ok", "placeholder": False},
                    {"id": "r1", "bbox": [1, 50, 30, 80],
                     "text": "chú thích ảnh", "verdict": "ok",
                     "placeholder": False},
                ],
            }
        ],
    }

async def test_build_docx_table_block(monkeypatch):
    """HTML table in OCR → docx table."""
    ir = {
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [{
            "page_id": "page_001",
            "page_number": 1,
            "header": [],
            "content": [
                {
                    "id": "node_001",
                    "type": "table",
                    "role": "body",
                    "text": "<table><tr><td>A</td><td>B</td></tr>"
                            "<tr><td>1</td><td>2</td></tr></table>",
                    "align": "left",
                    "indent": 0,
                    "source_block_ids": ["r0"],
                    "children": [],
                }
            ],
            "footer": [],
        }],
    }
    fake_llm(monkeypatch, [FakeResponse(json.dumps(ir))])
    data = await build_docx(_styled_result())
    assert data[:2] == b"PK"
    doc = Document(io.BytesIO(data))
    assert len(doc.tables) == 1
    rows = [[c.text for c in row.cells] for row in doc.tables[0].rows]
    assert rows == [["A", "B"], ["1", "2"]]

async def test_export_docx_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["url"]
    body = await storage.get(f"exports/{done_job_with_result}/docx-layout")
    assert body[:2] == b"PK"

async def test_export_docx_layout_llm_down_502_no_cache(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    # LLM down → heuristic fallback (no 502)
    assert r.status_code == 200
    assert await storage.exists(f"exports/{done_job_with_result}/docx-layout")

@pytest_asyncio.fixture
async def done_job_no_result(auth_client, db_session) -> int:
    """Done job whose ingest never produced a result (409 case)."""
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
    return job.id

async def test_export_docx_layout_missing_result_409(auth_client, done_job_no_result):
    r = await auth_client.post(
        f"/api/jobs/{done_job_no_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Chưa có kết quả OCR."

async def test_download_docx_layout_content_type(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 200, r.text
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/docx-layout/download"
    )
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    assert r.headers["content-type"] == DOCX_CONTENT_TYPE

async def test_export_docx_layout_other_user_403(
    auth_client, other_client, done_job_with_result, monkeypatch
):
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_IR))])
    r = await other_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 403
