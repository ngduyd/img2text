"""Docx dựng từ IR: heading theo level trong IR + page break theo trang OCR.

Trước: docx bỏ qua type_label/level (heading thành paragraph thường) và gộp
các trang cùng số cột vào một section → mất ranh giới trang gốc.
"""

import io
import re
import zipfile

from app.services.ir import spec_ir
from app.services.render_docx import render_docx_ir
from app.services.render_md import render_md_ir


def _xml(data: bytes) -> str:
    raw = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    return re.sub(r"\s+", " ", raw)


def _region(rid, text, bbox):
    return {"id": rid, "bbox": bbox, "text": text, "verdict": "ok", "placeholder": False}


def _title_result() -> dict:
    """Trang có 1 dòng chữ TO (font 2x median) → phải là heading level 1."""
    return {"markdown": "", "pages": [{
        "index": 0, "width": 800, "height": 600,
        "regions": [
            _region("t", "TIEU DE", [10, 10, 500, 110]),      # cao 100, 1 dòng
            _region("b", "doan thuong mot\ndoan thuong hai", [10, 130, 700, 170]),
            _region("c", "doan thuong ba\nbon", [10, 180, 700, 220]),
        ],
    }]}


def test_ir_stores_heading_level():
    ir = spec_ir(_title_result())
    levels = {n["source_block_ids"][0]: n["render"]["style"]["level"]
              for n in ir["pages"][0]["content"]}
    assert levels["t"] == 1, levels


def test_md_uses_level_from_ir():
    md = render_md_ir(spec_ir(_title_result()))
    assert md.splitlines()[0] == "# TIEU DE"


def test_docx_heading_style_from_ir_level():
    xml = _xml(render_docx_ir(spec_ir(_title_result())))
    assert 'w:pStyle w:val="Heading1"' in xml or 'w:pStyle w:val="Heading 1"' in xml
    assert 'w:pStyle w:val="Heading1"' in xml.replace("Heading 1", "Heading1")


def test_docx_page_break_between_ocr_pages():
    """2 trang cùng 1 cột → 1 section nhưng phải có page break giữa 2 trang."""
    result = {"markdown": "", "pages": [
        {"index": 0, "width": 800, "height": 600,
         "regions": [_region("a", "trang mot", [10, 10, 500, 50])]},
        {"index": 1, "width": 800, "height": 600,
         "regions": [_region("b", "trang hai", [10, 10, 500, 50])]},
    ]}
    xml = _xml(render_docx_ir(spec_ir(result)))
    assert '<w:br w:type="page"/>' in xml
    assert xml.index("trang mot") < xml.index('w:type="page"') < xml.index("trang hai")
