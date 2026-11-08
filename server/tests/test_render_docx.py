"""render_docx tests: layout_spec renderer (0 LLM) → DOCX."""

import io
import json

import pytest
from pathlib import Path

from docx import Document

from app.services.render_docx import build_docx

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

class TestBuildDocxSpec:
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

    async def test_image_region_without_bbox_keeps_placeholder(self):
        """P2-2: image node thiếu bbox KHÔNG bị drop — marker vẫn render."""
        result = {"pages": [{"index": 0, "width": 800, "height": 600,
            "regions": [
                {"id": "r0", "bbox": [1, 2, 30, 40], "text": "Châu Á",
                 "verdict": "ok", "placeholder": False},
                {"id": "r1", "text": "", "verdict": "image_unextractable",
                 "placeholder": True},  # thiếu bbox
            ]}]}
        data = await build_docx(result, use_llm=False)
        doc = Document(io.BytesIO(data))
        assert any("[ảnh]" in p.text for p in doc.paragraphs)

# --- wave-3 (spec 2026-10-13): region cells-shape → docx table merge span ---

def _cells_result() -> dict:
    cells = [
        [{"text": "A", "rowspan": 2, "colspan": 1, "header": False},
         {"text": "B", "rowspan": 1, "colspan": 2, "header": False}],
        [{"text": "C", "rowspan": 1, "colspan": 1, "header": False}],
    ]
    return {"pages": [{"index": 0, "width": 800, "height": 600, "regions": [
        {"id": "r0", "bbox": [1, 2, 798, 200],
         "text": "A | B | B\nA | C",  # phẳng (kernel)
         "html": "<table><tr><td rowspan=\"2\">A</td><td colspan=\"2\">B</td></tr>"
                 "<tr><td>C</td></tr></table>",
         "cells": cells, "verdict": "ok", "placeholder": False}]}]}

async def test_cells_table_renders_gridspan_vmerge():
    """wave-3: cells-shape → docx table python-docx merge() thật —
    document.xml chứa gridSpan (colspan) + vMerge (rowspan)."""
    import zipfile

    data = await build_docx(_cells_result(), use_llm=False)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert "<w:tbl>" in xml
    assert "gridSpan" in xml and "vMerge" in xml  # B colspan=2, A rowspan=2
    doc = Document(io.BytesIO(data))
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert t.cell(0, 0).text.strip() == "A"
    assert t.cell(0, 1).text.strip() == "B"
    assert t.cell(1, 0).text.strip() == "A"  # vMerge tiếp tục
    assert t.cell(1, 1).text.strip() == "C"

async def test_html_only_region_keeps_old_path():
    """Region chỉ có html (cũ, không cells) → path regex cũ giữ nguyên."""
    result = {"pages": [{"index": 0, "width": 800, "height": 600, "regions": [
        {"id": "r0", "bbox": [1, 2, 798, 40],
         "text": "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>",
         "verdict": "ok", "placeholder": False}]}]}
    data = await build_docx(result, use_llm=False)
    doc = Document(io.BytesIO(data))
    assert len(doc.tables) == 1
    rows = [[c.text for c in row.cells] for row in doc.tables[0].rows]
    assert rows == [["A", "B"], ["1", "2"]]


# ---------------------------------------------------------------- layout spec (phase 1)
SAMPLES = Path(__file__).parent / "fixtures" / "layout_samples"


def _sample(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


async def test_build_docx_spec_2col_sections_and_cols():
    """2 cột → 1 section liên tục + w:cols/@w:num=2 + indent + tab stop."""
    import zipfile

    data = await build_docx(_sample("2col"), use_llm=False)
    doc = Document(io.BytesIO(data))
    assert len(doc.sections) == 1
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert '<w:cols w:num="2"' in xml
    indented = [p for p in doc.paragraphs if (p.paragraph_format.left_indent or 0) > 0]
    assert indented and indented[0].text.startswith("Đoạn thụt lề")
    tabbed = [p for p in doc.paragraphs if len(p.paragraph_format.tab_stops) == 1]
    assert tabbed and tabbed[0].text.startswith("Ký tên:")
    assert [p.text for p in doc.paragraphs][:3] == [
        "Cột trái đoạn 1 dòng 1.\nCột trái đoạn 1 dòng 2.",
        "Đoạn thụt lề dòng 1.\nĐoạn thụt lề dòng 2.",
        "Ký tên: .....\tTrần B",
    ]


async def test_build_docx_spec_form_tab_leader_dots():
    """Form → tab stop leader DOTS cho từng hàng nhãn/giá trị."""
    from docx.enum.text import WD_TAB_LEADER

    data = await build_docx(_sample("form"), use_llm=False)
    doc = Document(io.BytesIO(data))
    stops = [list(p.paragraph_format.tab_stops) for p in doc.paragraphs]
    leaders = [s[0].leader for s in stops if s]
    assert leaders == [WD_TAB_LEADER.DOTS] * 3
    assert doc.tables and doc.tables[0].cell(0, 0).text == "STT"


async def test_build_docx_spec_1col_single_section_no_cols_override():
    """1 cột → 1 section, w:cols/@w:num=1, text order giữ nguyên."""
    import zipfile

    data = await build_docx(_sample("1col"), use_llm=False)
    doc = Document(io.BytesIO(data))
    assert len(doc.sections) == 1
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert '<w:cols w:num="1"' in xml
    texts = [p.text for p in doc.paragraphs]
    assert texts[0] == "CHƯƠNG 1: MỞ ĐẦU"
    assert "[ảnh]" in texts

# ---------------------------------------------------------------- crop embed
import base64
import zipfile

from app.services.render_docx import render_docx_spec

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg=="
)

def _media_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]

def _image_result() -> dict:
    """1 block image, bbox 200x100 (r1)."""
    return {"pages": [{"index": 0, "width": 800, "height": 600, "regions": [
        {"id": "r1", "bbox": [10, 10, 210, 110], "text": "",
         "verdict": "image_unextractable", "placeholder": True}]}]}

async def test_render_docx_spec_embeds_crop_by_bbox_width():
    """crops có rid → 1 inline image, width = bbox w px → twips, không placeholder."""
    from docx.shared import Twips

    data = render_docx_spec(_image_result(), crops={"r1": PNG_1PX})
    doc = Document(io.BytesIO(data))
    assert len(doc.inline_shapes) == 1
    assert "[ảnh]" not in "\n".join(p.text for p in doc.paragraphs)
    # Toạ độ px scale theo khung trang suy từ chính trang gốc (A4 + lề của scan).
    from app.services.render_docx import TWIPS_PER_PX, _page_geometry
    page = _image_result()["pages"][0]
    geo = _page_geometry(page)
    expected = Twips(round(200 * TWIPS_PER_PX * geo.scale))
    assert abs(doc.inline_shapes[0].width - expected) <= expected * 0.02

async def test_render_docx_spec_missing_crop_keeps_placeholder():
    """crops thiếu rid → placeholder [ảnh] còn, không crash."""
    data = render_docx_spec(_image_result(), crops={"other": PNG_1PX})
    doc = Document(io.BytesIO(data))
    assert not doc.inline_shapes
    assert "[ảnh]" in "\n".join(p.text for p in doc.paragraphs)

async def test_build_docx_crop_loader_embeds():
    """build_docx crop_loader trả bytes → ảnh nhúng (media part)."""
    async def loader(rid: str) -> bytes:
        return PNG_1PX

    data = await build_docx(_image_result(), crop_loader=loader)
    assert _media_names(data)
    assert len(Document(io.BytesIO(data)).inline_shapes) == 1

async def test_build_docx_crop_loader_error_keeps_placeholder():
    """loader raise → placeholder, không crash."""
    async def loader(rid: str) -> bytes:
        raise RuntimeError("storage down")

    data = await build_docx(_image_result(), crop_loader=loader)
    assert _media_names(data) == []
    assert "[ảnh]" in "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def test_formula_block_becomes_omml_not_text():
    """Công thức $$...$$ → OMML (Word render thật), không in LaTeX thô."""
    import io
    import zipfile

    from app.services.render_docx import render_docx_spec

    result = {"pages": [{"index": 0, "width": 640, "height": 906, "page_flag": "ok",
                         "markdown": "", "regions": [
                             {"id": "f", "bbox": [283, 100, 348, 136], "verdict": "ok",
                              "text": " $$ E_{n}=\\frac{n^{2}h^{2}}{8m_{e}L^{2}} $$ "},
                         ]}]}
    xml = zipfile.ZipFile(io.BytesIO(render_docx_spec(result))).read(
        "word/document.xml").decode()
    assert "<m:oMath>" in xml
    assert "\\frac" not in xml
    assert "$$" not in xml

def test_page_geometry_margins_from_content_and_a4():
    """Trang gốc 1242x1713 px (A4 @150dpi), lề trắng ~90px → khung A4, lề quy đổi
    sang twips, vùng chữ rộng hơn 6in của template (job 86: ép 6in làm chữ phải
    thu 35% mới vừa → tràn trang)."""
    from app.services.render_docx import A4_W, TWIPS_PER_PX, _page_geometry

    page = {"width": 1242, "height": 1713, "content": [
        {"render": {"bbox_exact": [90.0, 100.0, 1150.0, 130.0]}},
        {"render": {"bbox_exact": [90.0, 130.0, 1120.0, 160.0]}},
    ]}
    geo = _page_geometry(page)
    scale = A4_W / (1242 * TWIPS_PER_PX)
    assert geo.scale == pytest.approx(scale)
    assert geo.margins[0] == round(90 * TWIPS_PER_PX * scale)   # lề trái = x0 nhỏ nhất
    assert geo.margins[1] == round((1242 - 1150) * TWIPS_PER_PX * scale)
    assert geo.text_width == pytest.approx(A4_W - geo.margins[0] - geo.margins[1])
    assert geo.text_width > 8640   # rộng hơn 6in template cũ


def test_page_metrics_font_from_line_box_not_block_height():
    """Cỡ chữ suy từ HỘP DÒNG (bbox height / số dòng), không từ chiều cao block
    hay khoảng cách đỉnh-block: block VLM là cả đoạn nhiều dòng (job 86: đỉnh
    block cách 83px → font 16pt → 5 trang; hộp dòng 38,5px → 9,2pt → 1 trang)."""
    from app.services.render_docx import (
        LINE_BOX_TO_FONT,
        PT_PER_PX,
        _page_geometry,
        _page_metrics,
    )

    page = {"width": 1242, "height": 1713, "content": [
        # 1 đoạn 4 dòng: bbox cao 4×38 = 152px, đỉnh block cách nhau rất xa
        {"render": {"kind": "text", "bbox_exact": [90.0, 100.0, 1150.0, 252.0],
                    "lines": ["a", "b", "c", "d"]}},
        {"render": {"kind": "text", "bbox_exact": [90.0, 400.0, 1150.0, 552.0],
                    "lines": ["e", "f", "g", "h"]}},
    ]}
    geo = _page_geometry(page)
    font_pt, pitch_pt = _page_metrics(page, geo)
    assert font_pt == pytest.approx(38.0 * PT_PER_PX * geo.scale * LINE_BOX_TO_FONT)
    assert pitch_pt == pytest.approx(font_pt * 1.2)
    assert font_pt < 12.0   # không phình theo chiều cao block (152px)



def test_inline_latex_underline_becomes_real_underline_run():
    """VLM trả `$ \\underline{curb} $` trong text (job 86) → docx phải là run gạch
    chân, KHÔNG in ra markup LaTeX; md cũng không còn `$`."""
    from docx import Document
    from app.services.ir import spec_ir
    from app.services.render_docx import render_docx_ir
    from app.services.render_md import render_md_ir

    result = {"pages": [{"index": 1, "width": 800, "height": 600, "regions": [{
        "id": "p1_b0", "bbox": [40, 40, 760, 90], "verdict": "ok",
        "text": "The word  $ \\underline{curb} $ in paragraph 2 is OPPOSITE in meaning",
    }]}]}
    ir = spec_ir(result)
    node = ir["pages"][0]["content"][0]
    assert "$" not in node["text"] and "underline{" not in node["text"]
    # "The word  " = 10 ký tự → span đúng vị trí "curb" trong text phẳng
    assert node["render"]["underline"] == [{"line": 0, "start": 10, "end": 14}]

    doc = Document(io.BytesIO(render_docx_ir(ir)))
    runs = [r for p in doc.paragraphs for r in p.runs]
    assert "".join(r.text for r in runs).startswith("The word  curb in paragraph 2")
    assert [r.text for r in runs if r.underline] == ["curb"]
    assert "$" not in render_md_ir(ir)


def test_plain_inline_tex_strips_math_without_underline():
    from app.services.layout_spec import plain_inline_tex

    plain, spans = plain_inline_tex("gọi là $x^2 + y$ nhé")
    assert plain == "gọi là x^2 + y nhé" and spans == []


def test_page_metrics_ignores_table_and_image_blocks():
    """Table/image có bbox cả khối (lines=1) → nếu tính vào hộp dòng thì font
    toàn trang bị thổi lên (job 88: bảng spec 900px ⇒ bảng tràn 2 trang)."""
    from app.services.render_docx import (
        LINE_BOX_TO_FONT,
        PT_PER_PX,
        _page_geometry,
        _page_metrics,
    )

    page = {"width": 1242, "height": 1713, "content": [
        {"render": {"kind": "text", "bbox_exact": [90.0, 100.0, 1150.0, 140.0],
                    "lines": ["một dòng"]}},
        {"render": {"kind": "table", "bbox_exact": [90.0, 200.0, 1150.0, 1100.0], "lines": []}},
        {"render": {"kind": "image", "bbox_exact": [90.0, 1150.0, 500.0, 1600.0], "lines": []}},
    ]}
    geo = _page_geometry(page)
    font_pt, _ = _page_metrics(page, geo)
    # đúng bằng công thức cho hộp dòng 40px (KHÔNG dính 900px của bảng/image)
    assert font_pt == pytest.approx(40 * PT_PER_PX * geo.scale * LINE_BOX_TO_FONT)

def test_per_page_geometry_and_font():
    """PDF trộn trang ngang/dọc (job 90: chứng chỉ ngang 2339px rồi 20 trang text
    dọc 1654px) — geometry + cỡ chữ phải theo TỪNG trang, không lấy trang 1."""
    import io

    from docx import Document
    from docx.shared import Pt
    from app.services.ir import spec_ir
    from app.services.render_docx import render_docx_ir

    def page(idx, w, h, y):
        return {"index": idx, "width": w, "height": h, "regions": [{
            "id": f"p{idx}_b0", "bbox": [60, y, w - 60, y + 60], "verdict": "ok",
            "text": "Dòng văn bản của trang",
        }]}

    result = {"pages": [page(1, 2339, 1653, 100), page(2, 1654, 2339, 100)]}
    doc = Document(io.BytesIO(render_docx_ir(spec_ir(result))))
    sizes = {
        round(r.font.size.pt, 1)
        for p in doc.paragraphs for r in p.runs if r.font.size is not None
    }
    # trang 1 (ngang, hộp dòng 60/1 ⇒ 8pt sàn) khác trang 2 (60px/1654 ⇒ ~10,8pt)
    assert len(sizes) >= 2, sizes
    assert min(sizes) == pytest.approx(8.0)
    assert max(sizes) > 8.0
    # mỗi trang 1 section với page size riêng (A4 dọc cho trang 2)
    assert len(doc.sections) >= 2
