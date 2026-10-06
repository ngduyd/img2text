"""Plan D2: docx-layout export via LLM layout plan (services/llm_docx).

No live LLM: httpx.AsyncClient is monkeypatched to canned responses.
Covers: render (zip magic + python-docx heading/columns), LLM down →
LLMLayoutError → route 502 (no cache), missing result → 409 exact,
download Content-Type, owner-or-admin, response_format retry.
"""

import io
import json

import httpx
import pytest
import pytest_asyncio
from docx import Document
from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, User
from app.services import llm_docx
from app.services.llm_docx import LLMLayoutError, build_layout_docx

from tests.test_jobs_read import other_client  # noqa: F401

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

FAKE_PLAN = {
    "columns": "two",
    "blocks": [
        {"id": "r0", "col": "full", "style": "h1"},
        {"id": "r1", "col": "left", "style": "body"},
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
    """Patch httpx.AsyncClient as llm_docx sees it; returns recorded calls.

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

        async def post(self, url, json=None):
            calls.append((url, dict(json or {})))  # copy: route pops keys
            resp = responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp

    monkeypatch.setattr(llm_docx.httpx, "AsyncClient", Client)
    return calls


def _cell_texts(doc) -> list[str]:
    return [
        p.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
        for p in cell.paragraphs
    ]


# --- build_layout_docx unit ---

async def test_build_layout_docx_renders_plan(
    monkeypatch, VALID_RESULT_JSONB
):
    calls = fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_PLAN))])
    data = await build_layout_docx(VALID_RESULT_JSONB, [(800, 600)])
    assert data[:2] == b"PK"  # zip container
    with io.BytesIO(data) as buf:
        doc = Document(buf)
    assert len(doc.tables) == 1  # two-column layout table
    merged = doc.tables[0].rows[0].cells[0]
    assert merged.text == "Xin chào"  # full-width row (merged cells)
    assert merged.paragraphs[0].style.name == "Heading 1"
    assert "[ảnh]" in _cell_texts(doc)  # image block → placeholder
    # prompt payload: model + temperature 0 + response_format + input JSON
    url, payload = calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == settings.llm_model
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    assert '"width": 800' in payload["messages"][0]["content"]
    assert '"r0"' in payload["messages"][0]["content"]


async def test_build_layout_docx_llm_down_raises(monkeypatch, VALID_RESULT_JSONB):
    fake_llm(
        monkeypatch,
        [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
    )
    with pytest.raises(LLMLayoutError):
        await build_layout_docx(VALID_RESULT_JSONB, [(800, 600)])


async def test_build_layout_docx_retries_without_response_format(
    monkeypatch, VALID_RESULT_JSONB
):
    plan = {"columns": "single", "blocks": [{"id": "r0", "col": "full", "style": "h1"}]}
    calls = fake_llm(
        monkeypatch,
        [
            FakeResponse(status_code=400, text="response_format unsupported"),
            FakeResponse(json.dumps(plan)),
        ],
    )
    data = await build_layout_docx(VALID_RESULT_JSONB, [(800, 600)])
    assert data[:2] == b"PK"
    assert "response_format" in calls[0][1]
    assert "response_format" not in calls[1][1]


# --- export route ---

async def test_export_docx_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_PLAN))])
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
    assert r.status_code == 502
    assert r.json()["detail"] == "Không kết nối LLM máy chủ."
    assert not await storage.exists(f"exports/{done_job_with_result}/docx-layout")


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
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_PLAN))])
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
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_PLAN))])
    r = await other_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 403
