"""Preview HTML phải khớp bản docx-layout (không như mammoth: mất math/tab)."""

import pytest

from app.services.render_html_spec import render_html_spec

pytestmark = pytest.mark.nodb


def _result(regions, w=640, h=906):
    return {"pages": [{"index": 0, "width": w, "height": h, "page_flag": "ok",
                       "markdown": "", "regions": regions}]}


def test_formula_becomes_mathml_not_raw_latex():
    out = render_html_spec(_result([
        {"id": "f", "bbox": [283, 100, 348, 136], "verdict": "ok",
         "text": " $$ E_{n}=\\frac{n^{2}h^{2}}{8m_{e}L^{2}} $$ "},
    ]))
    assert "<math" in out and "<msub>" in out
    assert "\\frac" not in out


def test_two_sided_header_keeps_both_sides():
    out = render_html_spec(_result([
        {"id": "l", "bbox": [64, 36, 241, 63], "verdict": "ok",
         "text": "BỘ GIÁO DỤC VÀ ĐÀO TẠO"},
        {"id": "r", "bbox": [293, 43, 559, 95], "verdict": "ok",
         "text": "KỲ THI CHỌN HỌC SINH GIỎI QUỐC GIA"},
        {"id": "body", "bbox": [48, 186, 592, 266], "verdict": "ok",
         "text": "Thân bài một đoạn dài đủ để nhận canh đều hai bên trái phải."},
    ]))
    assert 'class="row"' in out
    assert "BỘ GIÁO DỤC VÀ ĐÀO TẠO" in out and "KỲ THI CHỌN HỌC SINH GIỎI" in out
    assert "text-align:justify" in out          # thân bài canh đều


def test_image_uses_crop_url_when_available():
    out = render_html_spec(
        _result([{"id": "img", "bbox": [345, 500, 583, 700], "verdict": "ok",
                  "text": "", "placeholder": True}]),
        crop_urls={"img": "https://s3/crop.png"},
    )
    assert '<img src="https://s3/crop.png"' in out


def test_heading_gets_class_and_text_escaped():
    out = render_html_spec(_result([
        {"id": "h", "bbox": [46, 40, 400, 90], "verdict": "ok",
         "text": "Câu I"},
        {"id": "x", "bbox": [46, 200, 590, 230], "verdict": "ok",
         "text": "a < b & c"},
    ]))
    assert "a &lt; b &amp; c" in out
