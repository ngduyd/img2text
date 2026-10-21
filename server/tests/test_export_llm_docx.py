"""docx-layout export route (layout_spec render, 0 LLM).

Covers: render (zip magic), missing result → 409 exact, download
Content-Type, owner-or-admin. FakeResponse/fake_llm/FAKE_IR còn ở đây vì
test khác import làm helper; render không còn gọi LLM.
"""

import httpx
import pytest_asyncio
from sqlalchemy import select

from app.core.models import Job, User

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


FAKE_IR_HTML = "<h2>Xin chào</h2><p>Nội dung</p>"

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
    """Patch httpx.AsyncClient toàn cục; returns recorded calls."""
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


def _cell_texts(doc) -> list[str]:
    return [
        p.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
        for p in cell.paragraphs
    ]


# --- export route ---

async def test_export_docx_layout_happy(
    auth_client, done_job_with_result, storage, monkeypatch
):
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["url"]
    body = await storage.get(f"exports/{done_job_with_result}/docx-layout")
    assert body[:2] == b"PK"

async def test_export_docx_layout_reused_cache(
    auth_client, done_job_with_result, storage, monkeypatch
):
    """Render tất định (0 LLM) → lần 2 đọc cache, cùng bytes."""
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
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
    r = await other_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 403

