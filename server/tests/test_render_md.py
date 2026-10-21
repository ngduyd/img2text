"""render_md tests: layout_spec renderer (0 LLM) + heuristic band fallback."""

import json
from pathlib import Path

from app.core.schemas import IMAGE_MARKER
from app.services.render_md import build_md

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

class TestBuildMDSpec:
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

    async def test_build_md_table_block(self):
        """HTML table in OCR → md table."""
        out = await build_md(_ocr_result(), use_llm=False)
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

def test_crop_presign_expiry_reduced():
    """P2 #19 (spec 2026-10-16): crop presign window 24h → 1h, configurable qua settings."""
    from app.core.config import settings
    assert settings.crop_presign_expires == 3600

# ---------------------------------------------------------------- layout spec (phase 1)
SAMPLES = Path(__file__).parent / "fixtures" / "layout_samples"


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def md_order_left_then_right(out: str) -> bool:
    return out.index("Ký tên: .....") < out.index("Cột phải đoạn 1 dòng 1")

async def test_build_md_spec_2col_reads_left_column_first():
    """Layout spec: đọc HẾT cột trái rồi mới sang cột phải (không trộn dòng)."""
    out = await build_md(_sample("2col"), use_llm=False)
    assert any(ln.startswith(" ") for ln in out.splitlines())
    assert md_order_left_then_right(out)
    for ln in out.splitlines():
        assert not ("Cột trái" in ln and "Cột phải" in ln), ln
    assert out.endswith("\n") and not out.endswith("\n\n")

async def test_build_md_spec_2col_tab_only_within_tab_block():
    """TAB chỉ trong block nhãn+giá trị (Ký tên / Trần B), không nối 2 cột."""
    out = await build_md(_sample("2col"), use_llm=False)
    assert [ln for ln in out.splitlines() if "\t" in ln] == [
        " Ký tên: .....\tTrần B"   # indent_px 20 → 1 space
    ]

async def test_build_md_spec_form_keeps_dots():
    """Form: dấu chấm '.....' giữ nguyên + TAB giữa nhãn và giá trị."""
    out = await build_md(_sample("form"), use_llm=False)
    assert "....." in out
    assert "Họ và tên: .........\tNguyễn Văn A" in out
    assert "Ngày sinh: .........\t01/01/1990" in out
    assert "| STT | Nội dung |" in out      # table qua _cells_md
    assert out.endswith("\n")

async def test_build_md_spec_1col_center_and_heading():
    """1 cột: dòng căn giữa có space đầu dòng, heading có '#', marker ảnh giữ."""
    out = await build_md(_sample("1col"), use_llm=False)
    lines = out.splitlines()
    center = next(ln for ln in lines if "TIÊU ĐỀ GIỮA" in ln)
    assert center.startswith("    ")
    assert "## CHƯƠNG 1: MỞ ĐẦU" in out
    assert IMAGE_MARKER.format(region_id="r4") in out
    assert [ln for ln in lines if ln.strip()][0].startswith("## ")
