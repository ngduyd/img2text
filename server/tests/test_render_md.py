"""render_md tests: IR → LLM render → markdown + fallback geometry-aware."""

import json
from pathlib import Path

import httpx
import pytest

from app.services.render_md import RENDER_MD_PROMPT, build_md

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

class TestCoverageFailKeepsHeuristic:
    """Wave-4 #8: COVERAGE fail → GIỮ heuristic render (không stub 0 blocks
    "xóa đầu ra"); ir_sink (→ job.ir_json) KHÔNG bị overwrite; warning logged."""

    @staticmethod
    def _coverage_fail_ir() -> dict:
        # cover r0, bỏ r1 → coverage sai
        return {
            "document_id": "doc_001", "schema_version": "1.0",
            "pages": [{
                "page_id": "page_001", "page_number": 1, "header": [],
                "content": [{
                    "id": "node_001", "type": "table", "role": "unknown",
                    "source_block_ids": ["r0"], "bbox": [1, 2, 798, 40],
                    "children": [],
                }],
                "footer": [],
            }],
        }

    async def test_coverage_fail_renders_heuristic_not_stub(
        self, monkeypatch, caplog
    ):
        caplog.set_level("WARNING", logger="render_md")
        fake_llm(monkeypatch, [FakeResponse(json.dumps(self._coverage_fail_ir()))])
        out = await build_md(_ocr_result())
        assert "chú thích" in out  # heuristic có nội dung, KHÔNG phải stub rỗng
        assert any(
            "HEURISTIC FALLBACK" in r.getMessage() for r in caplog.records
        )

    async def test_coverage_fail_keeps_old_ir_sink(self, monkeypatch):
        """ir_sink cũ (lần render trước) không bị stub 0-block ghi đè."""
        old_ir = {"document_id": "old_doc", "schema_version": "1.0", "pages": []}
        sink = dict(old_ir)
        fake_llm(monkeypatch, [FakeResponse(json.dumps(self._coverage_fail_ir()))])
        out = await build_md(_ocr_result(), ir_sink=sink)
        assert "chú thích" in out
        assert sink == old_ir  # giữ nguyên cũ

class TestBuildMDFromIR:
    async def test_build_md_ir_happy(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        out = await build_md(_ocr_result())
        assert out == _md_response()  # render markdown tốt giữ nguyên

    async def test_render_envelope_output_unwrapped(self, monkeypatch):
        """Render trả envelope {\"output\": md} → unwrap đúng md."""
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse('{"output":"## X"}'),
        ])
        out = await build_md(_ocr_result())
        assert out == "## X"

    async def test_render_json_missing_field_falls_back(self, monkeypatch):
        """JSON thiếu field output/markdown → LLMError → heuristic."""
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse('{"foo":"bar"}'),
        ])
        out = await build_md(_ocr_result())
        assert "chú thích" in out  # heuristic, không phải "{...}"
        assert not out.lstrip().startswith("{")

    async def test_build_md_render_echo_ir_json_fallback(self, monkeypatch):
        """Render LLM echo IR JSON → LLMError → heuristic (chứa text OCR)."""
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse('{"document_id":"x","pages":[]}'),
        ])
        out = await build_md(_ocr_result())
        assert "chú thích" in out  # text OCR thật từ heuristic
        assert not out.lstrip().startswith("{")

    async def test_build_md_heading_rendered(self, monkeypatch):
        fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        out = await build_md(_ocr_result())
        assert "# Tiêu đề" in out

    async def test_build_md_llm_down_fallback(self, monkeypatch):
        """LLM down → heuristic fallback (no raise)."""
        # S2: page attempt + retry + full-fallback = 3×_chat, mỗi retry 1 → 6
        fake_llm(monkeypatch, [httpx.ConnectError("refused")] * 6)
        out = await build_md(_ocr_result())  # no raise
        assert out  # fallback output

    async def test_build_md_no_llm(self):
        """use_llm=False → pure heuristic."""
        out = await build_md(_ocr_result(), use_llm=False)
        assert out

    async def test_image_region_without_bbox_keeps_marker(self):
        """P2-2: image node thiếu bbox KHÔNG bị drop — marker vẫn render."""
        result = {"pages": [{"index": 0, "width": 800, "height": 600,
            "regions": [
                {"id": "r0", "bbox": [1, 2, 30, 40], "text": "Châu Á",
                 "verdict": "ok", "placeholder": False},
                {"id": "r1", "text": "", "verdict": "image_unextractable",
                 "placeholder": True},  # thiếu bbox
            ]}]}
        out = await build_md(result, use_llm=False)
        # strengthen: đúng IMAGE_MARKER format (exports._materialize_crops pin)
        from app.core.schemas import IMAGE_MARKER
        assert IMAGE_MARKER.format(region_id="r1") in out

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

    async def test_render_call_no_response_format_ir_call_has(self, monkeypatch):
        """json_mode: IR call CÓ response_format, render call KHÔNG."""
        calls = fake_llm(monkeypatch, [
            FakeResponse(json.dumps(_ir_response())),
            FakeResponse(_md_response()),
        ])
        await build_md(_ocr_result())
        assert "response_format" in calls[0][1]   # llm_ir → json_mode=True
        assert "response_format" not in calls[1][1]  # llm_render_md → False

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

    async def test_cells_shape_region_renders_pipe_table_heuristic(self):
        """wave-3: region cells-shape (text phẳng + html + cells, kernel
        batch) → heuristic render pipe table GFM (không html thô)."""
        cells = [
            [{"text": "A", "rowspan": 1, "colspan": 1, "header": True},
             {"text": "B", "rowspan": 1, "colspan": 1, "header": True}],
            [{"text": "1", "rowspan": 1, "colspan": 1, "header": False},
             {"text": "2", "rowspan": 1, "colspan": 1, "header": False}],
        ]
        result = {"pages": [{"index": 0, "width": 800, "height": 600,
            "regions": [
                {"id": "r0", "bbox": [1, 2, 798, 40],
                 "text": "A | B\n1 | 2",  # phẳng
                 "html": "<table><tr><td>A</td><td>B</td></tr>"
                         "<tr><td>1</td><td>2</td></tr></table>",
                 "cells": cells, "verdict": "ok", "placeholder": False},
            ]}]}
        out = await build_md(result, use_llm=False)
        assert "| A | B |" in out
        assert "| --- | --- |" in out  # strengthen: separator GFM
        assert "| 1 | 2 |" in out
        assert "<table" not in out

    async def test_cells_shape_colspan_repeats_in_heuristic_md(self):
        """P2-1 mirror: cells-shape region có colspan → heuristic pipe LẶP ô
        (giống kernel _table_cells_to_md); parse html sẽ mất colspan."""
        cells = [
            [{"text": "x", "rowspan": 1, "colspan": 2, "header": True}],
            [{"text": "y", "rowspan": 1, "colspan": 1, "header": False},
             {"text": "z", "rowspan": 1, "colspan": 1, "header": False}],
        ]
        result = {"pages": [{"index": 0, "width": 800, "height": 600,
            "regions": [
                {"id": "r0", "bbox": [1, 2, 798, 40],
                 "text": "x\ny | z",
                 "html": "<table><tr><td colspan=\"2\">x</td></tr>"
                         "<tr><td>y</td><td>z</td></tr></table>",
                 "cells": cells, "verdict": "ok", "placeholder": False},
            ]}]}
        out = await build_md(result, use_llm=False)
        assert "| x | x |" in out  # colspan=2 → lặp (mirror kernel)
        assert "| y | z |" in out
        assert "<table" not in out

class TestVariableZonesHeuristic:
    """Trang có zone biến thiên (header/content/footer khác nhau) → heuristic
    không bịa zone thừa. Deterministic (use_llm=False)."""

    def _result(self) -> dict:
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

    async def test_content_only_page_no_invented_header_footer(self):
        """Trang content-only (không header/footer) → không nhân đôi header,
        không thêm footer."""
        out = await build_md(self._result(), use_llm=False)
        assert out.count("TRƯỜNG THCS ABC") == 1  # header trang 0, không lặp trang 1
        assert "Nội dung phần hai" in out

    async def test_header_content_no_empty_footer(self):
        """Trang header+content (không footer) → không thêm footer rỗng/dấu thừa."""
        result = self._result()
        result["pages"].pop(1)
        out = await build_md(result, use_llm=False)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        assert lines == ["TRƯỜNG THCS ABC", "Nội dung phần một"]  # đúng 2 dòng, không thừa

def test_prompt_guards_empty_zones():
    """Pin guard vào RENDER_MD_PROMPT (tránh ai đó xóa)."""
    low = RENDER_MD_PROMPT.lower()
    assert "empty zones" in low
    assert "do not invent" in low
    assert "render nothing" in low


class TestLLMLogLoudness:
    """WS-UI fix: lỗi LLM phải log repr(exc) + attempt; fallback phải loud."""

    async def test_chat_failure_logs_repr_and_attempt(self, monkeypatch, caplog):
        caplog.set_level("WARNING", logger="render_md")
        # S2: page attempt + retry + full-fallback = 3×_chat, mỗi _chat retry 1 → 6
        fake_llm(monkeypatch, [httpx.ConnectError("conn refused")] * 6)
        out = await build_md(_ocr_result())  # LLMError nuốt → heuristic fallback
        assert out
        msgs = [r.getMessage() for r in caplog.records]
        assert any("llm call failed" in m and "attempt=" in m
                   and "ConnectError" in m for m in msgs), msgs

    async def test_fallback_warning_is_loud(self, monkeypatch, caplog):
        caplog.set_level("WARNING", logger="render_md")
        # S2: page attempt + retry + full-fallback = 3×_chat, mỗi _chat retry 1 → 6
        fake_llm(monkeypatch, [httpx.ConnectError("conn refused")] * 6)
        out = await build_md(_ocr_result())  # heuristic fallback, no raise
        assert out
        msgs = [r.getMessage() for r in caplog.records]
        assert any("HEURISTIC FALLBACK render" in m for m in msgs), msgs


def test_prompt_no_json_wrapper():
    """Prompt pin 'do NOT wrap in JSON' (model free hay bọc envelope)."""
    assert "do not wrap in json" in RENDER_MD_PROMPT.lower()

async def test_fallback_stats_counter(monkeypatch, caplog):
    """Fallback → _FALLBACK_STATS tăng + warning HEURISTIC FALLBACK tỉ lệ n/total."""
    from app.services import render_md
    monkeypatch.setattr(
        render_md, "_FALLBACK_STATS", {"fallback": 0, "total": 0}
    )
    caplog.set_level("WARNING", logger="app.services.render_md")
    # S2: 3×_chat (page + retry + full-fallback), mỗi _chat retry 1 → 6
    fake_llm(monkeypatch, [httpx.ConnectError("refused")] * 6)
    await build_md(_ocr_result())  # LLMError → heuristic
    stats = render_md._FALLBACK_STATS
    assert stats == {"fallback": 1, "total": 1}
    msg = [r.getMessage() for r in caplog.records if "tỉ lệ 1/1" in r.getMessage()]
    assert msg == ["HEURISTIC FALLBACK LLMError — tỉ lệ 1/1"]

async def test_render_empty_response_falls_back(monkeypatch):
    """Fake _chat trả rỗng → LLMError → heuristic (md thật từ OCR)."""
    fake_llm(monkeypatch, [
        FakeResponse(json.dumps(_ir_response())),
        FakeResponse("   "),
    ])
    out = await build_md(_ocr_result())
    assert "chú thích" in out  # heuristic content

def test_crop_presign_expiry_reduced():
    """P2 #19 (spec 2026-10-16): crop presign window 24h → 1h, configurable qua settings."""
    from app.core.config import settings
    assert settings.crop_presign_expires == 3600

# ---------------------------------------------------------------- layout spec (phase 1)
SAMPLES = Path(__file__).parent / "fixtures" / "layout_samples"


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


async def test_build_md_spec_2col_spaces_not_tabs():
    """Heuristic: thụt lề/căn cột bằng SPACE (không tab thô)."""
    out = await build_md(_sample("2col"), use_llm=False)
    assert "\t" not in out
    assert any(ln.startswith(" ") for ln in out.splitlines())
    assert "Cột trái đoạn 1 dòng 1." in out
    assert "Cột phải đoạn 1 dòng 1." in out


async def test_build_md_spec_form_keeps_dots():
    """Form: dấu chấm '.....' giữ nguyên trong md."""
    out = await build_md(_sample("form"), use_llm=False)
    assert "....." in out
    assert "Họ và tên: ........." in out
    assert "Nguyễn Văn A" in out
