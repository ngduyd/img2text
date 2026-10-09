"""render_md tests: IR → LLM render → markdown + fallback geometry-aware."""

import json

import httpx
import pytest

from app.services.render_md import build_md

from tests.test_export_llm_docx import FakeResponse

def _ocr_result() -> dict:
    return {
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "regions": [
                    {"id": "r0", "bbox": [1, 2, 798, 40],
                     "text": "<table><tr><td>A</td><td>B</td></tr>"
                             "<tr><td>1</td><td>2</td></tr></table>",
                     "verdict": "ok", "placeholder": False},
                    {"id": "r1", "bbox": [1, 60, 798, 100],
                     "text": "chú thích", "verdict": "ok", "placeholder": False},
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
                        "bbox": [1, 2, 798, 40],
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
                        "bbox": [1, 60, 798, 100],
                        "children": [],
                    },
                ],
                "footer": [],
            }
        ],
    }

def _md_response() -> str:
    return "# Tiêu đề\n\nNội dung đoạn văn"

def _md_table_response() -> str:
    return "| A | B |\n| --- | --- |\n| 1 | 2 |"

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

class TestBuildMDFromIR:
    async def test_build_md_ir_happy(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        out = await build_md(_ocr_result())
        assert "Tiêu đề" in out
        assert "Nội dung đoạn văn" in out

    async def test_build_md_heading_rendered(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        out = await build_md(_ocr_result())
        assert "# Tiêu đề" in out

    async def test_build_md_llm_down_fallback(self, monkeypatch):
        """LLM down → heuristic fallback (no raise)."""
        fake_llm(
            monkeypatch,
            [httpx.ConnectError("refused"), httpx.ConnectError("refused")],
        )
        out = await build_md(_ocr_result())  # no raise
        assert out  # fallback output

    async def test_build_md_no_llm(self):
        """use_llm=False → pure heuristic."""
        out = await build_md(_ocr_result(), use_llm=False)
        assert out

    async def test_prompt_requests_bbox(self, monkeypatch):
        """Cả structurize lẫn render prompt đều chỉ định bbox."""
        calls = fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        await build_md(_ocr_result())
        assert "bbox" in json.dumps(calls[0][1])
        # render prompt: bbox + page width trong page_dims
        assert "bbox" in json.dumps(calls[1][1])
        assert "800" in json.dumps(calls[1][1])

    async def test_build_md_bbox_filled_when_missing(self, monkeypatch):
        """Node thiếu bbox → validator union từ source_block_ids → render OK."""
        ir = _ir_response()
        del ir["pages"][0]["content"][0]["bbox"]
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(ir)),
            FakeResponse(_md_response()),
        ])
        out = await build_md(_ocr_result())
        assert "Tiêu đề" in out
        assert "Nội dung đoạn văn" in out

    async def test_build_md_table_block(self, monkeypatch):
        """HTML table in OCR → md table."""
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
                "bbox": [1, 2, 798, 40],
                "children": [],
            }
        ]
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(ir)),
            FakeResponse(_md_table_response()),
        ])
        out = await build_md(_ocr_result())
        assert "| A | B |" in out
        assert "| 1 | 2 |" in out
