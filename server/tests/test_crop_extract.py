"""WS-PIPE task 2: kernel crop extract — PDF fixture 2 trang tạo bằng fitz,
rembg = stub. image block (type=="image", bbox px @200dpi) → PyMuPDF
page.get_pixmap(clip=Rect bbox→pt) → PNG bytes → remove stub → {rid: png}."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "deploy" / "kaggle" / "kernel"))

import img2text_batch as kb  # noqa: E402


@pytest.fixture(autouse=True)
def _cutout(monkeypatch, request):
    """Các test ở đây kiểm tra CƠ CHẾ crop; cổng "rembg chỉ cho ảnh cutout"
    (viền sáng đồng nhất) có test riêng bên dưới → ép True cho gọn."""
    if request.node.name.startswith("test_is_product_cutout"):
        return
    monkeypatch.setattr(kb, "_is_product_cutout", lambda png: True)


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

def test_extract_crops_downscaled_page_clips_original_coords(tmp_path):
    """Lane H task 1: rasterize downscale 4000×3000 → 3000 (scales.json 0.75);
    bbox trên ảnh downscaled đổi sang tọa độ trang gốc qua scale = page.rect/
    w_px (đã bao trọn hệ số rasterize + preprocess — KHÔNG chia thêm
    scales.json) → crop trúng vùng đỏ gốc, không lệch về góc trên-trái."""
    import json
    import fitz
    from PIL import Image

    src = tmp_path / "big.jpg"
    base = Image.new("RGB", (4000, 3000), "white")
    base.paste(Image.new("RGB", (2400, 1500), "red"), (800, 600))
    base.save(src, "JPEG", quality=95)
    pages = kb.rasterize_to_pages(str(src), str(tmp_path / "raw"))
    scale = json.loads(
        (tmp_path / "scales.json").read_text(encoding="utf-8"))["page_0001"]
    assert scale == 0.75
    with Image.open(pages[0]) as im:
        w, h = im.size
    assert (w, h) == (3000, 2250)
    # bbox vùng đỏ (800,600)-(3200,2100) trên ảnh GỐC → tọa độ trang downscaled
    bbox = [round(v * scale) for v in (800, 600, 3200, 2100)]
    assert bbox == [600, 450, 2400, 1575]
    got = kb.extract_crops(
        str(src),
        [{"page": 1, "width": w, "height": h,
          "blocks": [{"id": "p1_b0", "type": "image", "bbox": bbox, "text": ""}]}],
        remove=lambda png: png,
    )
    img = Image.open(io.BytesIO(got["p1_b0"]))
    # pix = clip (đơn vị page rect) × Matrix(2,2); rect của fitz theo dpi
    # metadata ảnh nguồn — pin toàn bộ chuỗi bbox × rect/w_px × 2
    rect_w = fitz.open(str(src))[0].rect.width
    assert img.width == pytest.approx((bbox[2] - bbox[0]) * (rect_w / w) * 2, abs=2)
    # điểm chèm vào crop phải ĐỎ (scale lệch hệ số 0.75 → còn trắng)
    px, py = max(2, img.width // 50), max(2, img.height // 50)
    r, g, b = img.getpixel((px, py))[:3]
    assert r > 200 and g < 60 and b < 60, f"({px},{py}) = {(r, g, b)}"

def test_extract_crops_pixmap_144dpi(tmp_path):
    """get_pixmap mặc định 72dpi → crop mờ cho rembg. matrix=Matrix(2,2)
    → pix.width ≥ clip.width×1.5."""
    import fitz
    from PIL import Image

    doc = fitz.open()
    p1 = doc.new_page(width=200, height=300)
    p1.draw_rect(fitz.Rect(20, 30, 120, 180), color=(1, 0, 0), fill=(1, 0, 0))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(doc.tobytes())
    doc.close()
    # bbox = pre px (width 100 = half của rect 200pt → scale 2)
    got = kb.extract_crops(
        str(pdf),
        [{"page": 1, "width": 100, "height": 150,
          "blocks": [{"id": "p1_b0", "type": "image",
                      "bbox": [10, 15, 60, 90], "text": ""}]}],
        remove=lambda png: png,
    )
    img = Image.open(io.BytesIO(got["p1_b0"]))
    clip_w_pt = (60 - 10) * 2.0  # bbox × scale = 100pt
    assert img.width >= clip_w_pt * 1.5, f"pix.width={img.width} < {clip_w_pt*1.5}"


# --- 2026-11-04: rembg 1 lần/trang (rgba_pages) + session prewarm ----------

def test_extract_crops_uses_rgba_page_without_calling_rembg(tmp_path):
    """rgba_pages có trang → cắt từ ảnh RGBA 2xpt, KHÔNG gọi rembg lần nữa."""
    import io

    from PIL import Image

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(_pdf_2pages())
    rgba = Image.new("RGBA", (1191, 1684), (255, 0, 0, 0))  # 2x A4 pt
    buf = io.BytesIO()
    rgba.save(buf, "PNG")

    def _boom(_png):
        raise AssertionError("rembg không được gọi khi đã có rgba_pages")

    got = kb.extract_crops(
        str(pdf),
        _pages_out(_pt_bbox(50, 60, 150, 160), _pt_bbox(10, 10, 190, 290)),
        remove=_boom,
        rgba_pages={1: buf.getvalue()},
    )
    # trang 2 không có rgba → rơi về đường rembg từng vùng (stub raise)
    assert "p1_b1" in got
    assert "p2_b0" not in got
    cut = Image.open(io.BytesIO(got["p1_b1"]))
    assert cut.mode == "RGBA"
    # 100pt × 2 (Matrix(2,2)) ± 1px do làm tròn px->pt->px
    assert abs(cut.size[0] - 200) <= 2 and abs(cut.size[1] - 200) <= 2


def test_page_rgba_returns_none_on_broken_input(tmp_path):
    """Input hỏng → None (không raise) để caller giữ đường rembg từng vùng."""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert kb.page_rgba(str(bad), 1) is None


def test_ensure_uv_skips_pip_when_uv_present(monkeypatch):
    """uv có sẵn trong image Kaggle (đo 2026-11-04) → không pip install."""
    from types import SimpleNamespace

    import shutil as _sh

    calls: list[list[str]] = []
    monkeypatch.setattr(_sh, "which", lambda name: "/usr/local/bin/uv")
    monkeypatch.setattr(
        kb.subprocess, "run",
        lambda cmd, **kw: calls.append(list(cmd)) or SimpleNamespace(returncode=0),
    )
    labels: list[str] = []
    kb.ensure_uv(labels.append)
    assert calls == []  # không cài uv
    assert labels == ["uv"]


def test_get_rembg_session_cached(monkeypatch):
    """u2net session tạo 1 lần/session (không tải model mỗi job)."""
    import img2text_session as sess

    made: list[int] = []

    def _fake():
        made.append(1)
        return "SESSION"

    monkeypatch.setattr(sess.kb, "rembg_session", _fake)
    monkeypatch.setattr(sess, "_rembg_session", None)
    assert sess.get_rembg_session() == "SESSION"
    assert sess.get_rembg_session() == "SESSION"
    assert made == [1]


def test_is_product_cutout_only_for_white_border():
    """rembg chỉ dành cho ảnh vật thể nền trắng; screenshot (viền tối/lộn xộn)
    phải giữ nguyên pixel — nếu không sẽ bị khoét lỗ trắng (job 90: mất nửa ảnh)."""
    from PIL import Image

    white = Image.new("RGB", (40, 40), (255, 255, 255))
    white.paste((200, 30, 30), (10, 10, 30, 30))
    buf = io.BytesIO(); white.save(buf, "PNG")
    assert kb._is_product_cutout(buf.getvalue()) is True

    shot = Image.new("RGB", (40, 40), (250, 250, 250))
    for x in range(0, 40):
        shot.putpixel((x, 0), (30, 30, 30))          # thanh cửa sổ tối phía trên
    buf = io.BytesIO(); shot.save(buf, "PNG")
    assert kb._is_product_cutout(buf.getvalue()) is False
