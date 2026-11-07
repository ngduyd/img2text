"""IR là nguồn render DUY NHẤT: node mang text+style, md và docx đi từ IR.

Trước 2026-11-07: IR chỉ có id/type/bbox (không text) nên không thể dựng
layout; md/docx đọc thẳng layout_spec → hai đường khác nhau.
"""

import io
import re
import zipfile

from app.services.ir import DocumentIR, spec_ir
from app.services.render_docx import render_docx_ir, render_docx_spec
from app.services.render_md import render_md_ir, render_md_spec

RESULT = {
    "markdown": "# tài liệu",
    "pages": [
        {
            "index": 0,
            "width": 800,
            "height": 1000,
            "regions": [
                {"id": "r0", "bbox": [10, 20, 500, 60], "text": "TIEU DE LON",
                 "verdict": "ok", "placeholder": False},
                {"id": "r1", "bbox": [10, 100, 700, 160], "text": "Doan van thuong\nhai dong",
                 "verdict": "ok", "placeholder": False},
                {"id": "r2", "bbox": [10, 200, 300, 400], "text": "",
                 "verdict": "image_unextractable", "placeholder": True},
            ],
        }
    ],
}


def _docx_xml(data: bytes) -> str:
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    return re.sub(r"\s+", " ", xml)


def test_ir_node_carries_text_and_render_payload():
    ir = spec_ir(RESULT)
    DocumentIR.model_validate(ir)
    page = ir["pages"][0]
    assert page["width"] == 800.0
    assert page["columns"], "page phải mang columns để md căn lề"
    nodes = page["content"]
    assert all(n.get("render") for n in nodes)
    first = nodes[0]
    assert first["text"] == "TIEU DE LON"
    assert first["render"]["style"]["font_px"] > 0
    assert len(first["render"]["bbox_exact"]) == 4
    figure = nodes[-1]
    assert figure["render"]["kind"] == "image"
    assert figure["render"]["image_region_id"] == "r2"


def test_md_renders_from_ir_identically():
    assert render_md_spec(RESULT) == render_md_ir(spec_ir(RESULT))


def test_docx_renders_from_ir_identically():
    assert _docx_xml(render_docx_spec(RESULT)) == _docx_xml(
        render_docx_ir(spec_ir(RESULT))
    )


def test_md_reads_style_from_ir_not_from_result():
    """Sửa IR (không đụng result) → md đổi theo: chứng minh md KHÔNG tự suy lại
    layout từ result."""
    ir = spec_ir(RESULT)
    ir["pages"][0]["content"][1]["render"]["lines"] = ["DONG SUA TU IR"]
    md = render_md_ir(ir)
    assert "DONG SUA TU IR" in md
    assert "Doan van thuong" not in md


def test_legacy_ir_without_render_is_skipped():
    ir = {"document_id": "d", "schema_version": "1.0",
          "pages": [{"page_id": "0", "page_number": 1, "content": [
              {"id": "x", "type": "paragraph", "source_block_ids": ["r0"],
               "bbox": [0, 0, 10, 10], "text": "bo qua"}]}]}
    assert render_md_ir(ir) == ""
