"""render_docx tests: IR → LLM render (HTML) → DOCX + fallback."""

import io
import json

import httpx
import pytest
from docx import Document

from app.services.render_docx import RENDER_DOCX_PROMPT, build_docx

from tests.test_export_llm_docx import FakeResponse

def _ocr_result() -> dict:
    return {
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
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
        ]
    }

def _ir_response() -> dict:
    return {
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
                        "text": "Tiêu đề",
                        "align": "left",
                        "indent": 0,
                        "source_block_ids": ["r0"],
                        "bbox": [1, 2, 30, 40],
                        "children": [],
                    },
                    {
                        "id": "node_002",
                        "type": "paragraph",
                        "role": "body",
                        "text": "Nội dung đoạn văn",
                        "align": "left",
                        "indent": 0,
                        "source_block_ids": ["r1"],
                        "bbox": [1, 50, 30, 80],
                        "children": [],
                    },
                ],
                "footer": [],
            }
        ],
    }

def _zones_result() -> dict:
    """Trang 0 header+content (không footer), trang 1 content-only."""
    return {
        "pages": [
            {
                "index": 0, "width": 800, "height": 600,
                "regions": [
                    {"id": "h0", "bbox": [100, 5, 700, 30],
                     "text": "TRƯỜNG THCS ABC", "verdict": "ok",
                     "placeholder": False},
                    {"id": "c0", "bbox": [50, 60, 750, 100],
                     "text": "Nội dung phần một", "verdict": "ok",
                     "placeholder": False},
                ],
            },
            {
                "index": 1, "width": 800, "height": 600,
                "regions": [
                    {"id": "c1", "bbox": [50, 60, 750, 100],
                     "text": "Nội dung phần hai", "verdict": "ok",
                     "placeholder": False},
                ],
            },
        ]
    }

def _html_response() -> str:
    return "<h2>Tiêu đề</h2><p>Nội dung đoạn văn</p>"

def _html_table_response() -> str:
    return "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"

def fake_llm(monkeypatch, responses: list) -> list:
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

class TestBuildDocxFromIR:
    async def test_build_docx_ir_happy(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_html_response()),
        ])
        data = await build_docx(_ocr_result())
        assert data[:2] == b"PK"  # zip container
        doc = Document(io.BytesIO(data))
        texts = [p.text for p in doc.paragraphs]
        assert "Tiêu đề" in texts
        assert "Nội dung đoạn văn" in texts

    async def test_build_docx_render_echo_ir_json_fallback(self, monkeypatch):
        """Render LLM echo IR JSON → LLMError → heuristic (chứa text OCR)."""
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse('{"document_id":"x","pages":[]}'),
        ])
        data = await build_docx(_ocr_result())
        assert data[:2] == b"PK"
        doc = Document(io.BytesIO(data))
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "chú thích ảnh" in all_text  # text OCR thật từ heuristic
        assert not all_text.lstrip().startswith("{")

    async def test_build_docx_heading_style(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_html_response()),
        ])
        data = await build_docx(_ocr_result())
        doc = Document(io.BytesIO(data))
        headings = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert any("Tiêu đề" in h.text for h in headings)

    async def test_build_docx_llm_down_fallback(self, monkeypatch):
        """LLM down → heuristic fallback (no raise)."""
        fake_llm(
            monkeypatch,
            [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
        )
        data = await build_docx(_ocr_result())  # no raise
        assert data[:2] == b"PK"

    async def test_build_docx_no_llm(self):
        """use_llm=False → pure heuristic."""
        data = await build_docx(_ocr_result(), use_llm=False)
        assert data[:2] == b"PK"

    async def test_variable_zones_content_only_page_no_invented_header_footer(self):
        """Trang content-only → heuristic không nhân đôi header, không footer thừa."""
        data = await build_docx(_zones_result(), use_llm=False)
        texts = [p.text.strip() for p in Document(io.BytesIO(data)).paragraphs]
        assert texts.count("TRƯỜNG THCS ABC") == 1
        assert "Nội dung phần hai" in texts

    async def test_variable_zones_header_content_no_empty_footer(self):
        """Trang header+content (không footer) → không thêm footer rỗng."""
        result = _zones_result()
        result["pages"].pop(1)
        data = await build_docx(result, use_llm=False)
        texts = [p.text.strip() for p in Document(io.BytesIO(data)).paragraphs]
        assert [t for t in texts if t] == ["TRƯỜNG THCS ABC", "Nội dung phần một"]

    async def test_prompt_requests_bbox(self, monkeypatch):
        """Cả structurize lẫn render prompt đều chỉ định bbox."""
        calls = fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_html_response()),
        ])
        await build_docx(_ocr_result())
        assert "bbox" in json.dumps(calls[0][1])
        # render prompt: bbox + page width trong page_dims
        assert "bbox" in json.dumps(calls[1][1])
        assert "800" in json.dumps(calls[1][1])

    async def test_build_docx_bbox_filled_when_missing(self, monkeypatch):
        """Node thiếu bbox → validator union từ source_block_ids → render OK."""
        ir = _ir_response()
        del ir["pages"][0]["content"][0]["bbox"]
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(ir)),
            FakeResponse(_html_response()),
        ])
        data = await build_docx(_ocr_result())
        doc = Document(io.BytesIO(data))
        texts = [p.text for p in doc.paragraphs]
        assert "Tiêu đề" in texts
        assert "Nội dung đoạn văn" in texts

def test_prompt_guards_empty_zones():
    """Pin guard vào RENDER_DOCX_PROMPT (tránh ai đó xóa)."""
    low = RENDER_DOCX_PROMPT.lower()
    assert "empty zones" in low
    assert "do not invent" in low
    assert "render nothing" in low

    async def test_build_docx_table_block(self, monkeypatch):
        """HTML table in OCR → docx table."""
        ir = _ir_response()
        ir["pages"][0]["content"] = [
            {
                "id": "node_001",
                "type": "table",
                "role": "body",
                "text": "<table><tr><td>A</td><td>B</td></tr>"
                        "<tr><td>1</td><td>2</td></tr></table>",
                "align": "left",
                "indent": 0,
                "source_block_ids": ["r0"],
                "bbox": [1, 2, 30, 40],
                "children": [],
            }
        ]
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(ir)),
            FakeResponse(_html_table_response()),
        ])
        data = await build_docx(_ocr_result())
        doc = Document(io.BytesIO(data))
        assert len(doc.tables) == 1
        rows = [[c.text for c in row.cells] for row in doc.tables[0].rows]
        assert rows == [["A", "B"], ["1", "2"]]
