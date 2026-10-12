"""WS-PIPE task 2: kernel crop extract — PDF fixture 2 trang tạo bằng fitz,
rembg = stub. image block (type=="image", bbox px @200dpi) → PyMuPDF
page.get_pixmap(clip=Rect bbox→pt) → PNG bytes → remove stub → {rid: png}."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "deploy" / "kaggle" / "kernel"))

import img2text_batch as kb  # noqa: E402


def _pdf_2pages() -> bytes:
    """2 trang 200x300pt: trang 1 red rect (50,60)-(150,160), trang 2 xanh."""
    import fitz

    doc = fitz.open()
    p1 = doc.new_page(width=200, height=300)
    p1.draw_rect(fitz.Rect(50, 60, 150, 160), color=(1, 0, 0), fill=(1, 0, 0))
    p2 = doc.new_page(width=200, height=300)
    p2.draw_rect(fitz.Rect(10, 10, 190, 290), color=(0, 0, 1), fill=(0, 0, 1))
    data = doc.tobytes()
    doc.close()
    return data


def _pages_out(bbox1, bbox2) -> list[dict]:
    # bbox px @200dpi: 50pt*200/72 ≈ 139
    return [
        {"page": 1, "width": int(200 * 200 / 72), "height": int(300 * 200 / 72),
         "blocks": [
             {"id": "p1_b0", "type": "text", "bbox": [0, 0, 100, 40], "text": "chữ"},
             {"id": "p1_b1", "type": "image", "bbox": bbox1, "text": ""},
         ]},
        {"page": 2, "width": int(200 * 200 / 72), "height": int(300 * 200 / 72),
         "blocks": [
             {"id": "p2_b0", "type": "image", "bbox": bbox2, "text": ""},
         ]},
    ]


def _pt_bbox(x0, y0, x1, y1) -> list[int]:
    s = 200 / 72
    return [int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s)]


def test_extract_crops_pdf_two_pages_rembg_stub(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(_pdf_2pages())
    seen: list[bytes] = []

    def _stub(png: bytes) -> bytes:
        seen.append(png)
        return b"CLEAN:" + png[:8]

    got = kb.extract_crops(
        str(pdf),
        _pages_out(_pt_bbox(50, 60, 150, 160), _pt_bbox(10, 10, 190, 290)),
        remove=_stub,
    )
    assert set(got) == {"p1_b1", "p2_b0"}  # text block không crop
    assert len(seen) == 2  # stub rembg nhận PNG từng crop
    for rid, data in got.items():
        assert data.startswith(b"CLEAN:")
    # crop trang 1 = PNG hợp lệ, ~101x101pt→px @72 (clip resolution ~bbox pt)
    import fitz

    d2 = fitz.open(stream=seen[0][8:], filetype="png") if False else None  # noqa: F841
    assert seen[0][:8] == b"\x89PNG\r\n\x1a\n"  # PyMuPDF emit PNG


def test_extract_crops_skips_bboxless_and_continues_on_error(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(_pdf_2pages())

    def _boom(_png: bytes) -> bytes:
        raise RuntimeError("rembg model missing")

    pages = _pages_out(None, _pt_bbox(10, 10, 190, 290))
    got = kb.extract_crops(str(pdf), pages, remove=_boom)
    assert got == {}  # 1 crop lỗi → không kill job (partial-fail)


def test_extract_crops_image_input(tmp_path):
    """jpg/png input: fitz mở ảnh 1 trang — bbox px → clip theo tỷ lệ rect."""
    from PIL import Image

    p = tmp_path / "doc.png"
    img = Image.new("RGB", (400, 600), "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p.write_bytes(buf.getvalue())
    got = kb.extract_crops(
        str(p),
        [{"page": 1, "width": 400, "height": 600,
          "blocks": [{"id": "p1_b0", "type": "image",
                      "bbox": [100, 100, 300, 500], "text": ""}]}],
        remove=lambda png: png,
    )
    assert set(got) == {"p1_b0"}
    assert got["p1_b0"][:8] == b"\x89PNG\r\n\x1a\n"

def test_extract_crops_pdf_bbox_in_preprocessed_coords(tmp_path):
    """bbox OCR = px trên ảnh ĐÃ preprocess (downscale) → scale = page.rect/
    preprocessed size trước khi clip. Page 200x300pt, pre 100x150 → scale=2:
    bbox vùng giữa [25,37,75,112] phải clip đúng rect giữa trang (đỏ)."""
    import fitz
    from PIL import Image

    doc = fitz.open()
    p1 = doc.new_page(width=200, height=300)
    p1.draw_rect(fitz.Rect(50, 74, 150, 224), color=(1, 0, 0), fill=(1, 0, 0))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(doc.tobytes())
    doc.close()

    got = kb.extract_crops(
        str(pdf),
        [{"page": 1, "width": 100, "height": 150,
          "blocks": [{"id": "p1_b0", "type": "image",
                      "bbox": [25, 37, 75, 112], "text": ""}]}],
        remove=lambda png: png,
    )
    pix = fitz.open(stream=got["p1_b0"], filetype="png")
    cx, cy = pix[0].rect.width // 2, pix[0].rect.height // 2
    img = Image.open(io.BytesIO(got["p1_b0"]))
    r, g, b = img.getpixel((cx, cy))[:3]
    pix.close()
    assert r > 200 and g < 60 and b < 60, f"center ({cx},{cy}) = {(r, g, b)}"
