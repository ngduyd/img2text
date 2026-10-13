"""WS-PIPE task 4: render embed crop artifact.

md: marker → `![vùng {rid}]({presigned 24h})` khi storage có
exports/{id}/crops/{rid}.png (không có → giữ marker).
docx: html_to_docx img node → embed bytes crop trực tiếp (không phụ thuộc
URL); crop thiếu → img bị drop như cũ (không crash)."""

import base64
import io

from docx import Document

from app.core.schemas import IMAGE_MARKER
from app.services.html_to_docx import html_to_docx
from app.services.render_md import embed_crop_keys, embed_crop_urls

RID = "p1_b3"
KEY = f"exports/7/crops/{RID}.png"
MARKER = IMAGE_MARKER.format(region_id=RID)


class _FakeStorage:
    def __init__(self, keys: set[str]):
        self.keys = keys

    async def exists(self, key: str) -> bool:
        return key in self.keys

    async def presign_get(self, key: str, expires: int) -> str:
        assert key in self.keys and expires == 86400
        return f"https://cdn.example/{key}?sig=abc"


async def test_embed_crop_keys_marker_to_relative_key():
    """render: marker → RELATIVE key crops/{rid}.png — KHÔNG presign (URL
    24h baked vào artifact → hết hạn chết)."""
    md = f"chào\n\n{MARKER}\n\nhết"
    out = await embed_crop_keys(md, 7, _FakeStorage({KEY}))
    assert out == f"chào\n\n![vùng {RID}](crops/{RID}.png)\n\nhết"
    assert "http" not in out  # không hostname trong artifact

async def test_embed_crop_keys_ondemand_png_data_uri():
    """Wave-4 #9: crop artifact THIẾU → on-demand crop (route /regions/{rid}/crop
    logic) trả bytes → embed data-URI, marker biến mất."""
    md = f"chào\n\n{MARKER}\n\nhết"
    png = b"\x89PNG\r\n\x1a\nfake"

    async def _loader(rid: str) -> bytes:
        assert rid == RID
        return png

    out = await embed_crop_keys(md, 7, _FakeStorage(set()), crop_loader=_loader)
    b64 = base64.b64encode(png).decode("ascii")
    assert out == f"chào\n\n![vùng {RID}](data:image/png;base64,{b64})\n\nhết"

async def test_embed_crop_keys_ondemand_jpeg_data_uri():
    """JPEG bytes (get_or_make_crop cache) → data:image/jpeg."""
    jpg = b"\xff\xd8\xfffakejpg"

    async def _loader(rid: str) -> bytes:
        return jpg

    out = await embed_crop_keys(MARKER, 7, _FakeStorage(set()), crop_loader=_loader)
    b64 = base64.b64encode(jpg).decode("ascii")
    assert out == f"![vùng {RID}](data:image/jpeg;base64,{b64})"

async def test_embed_crop_keys_budget_cap_keeps_marker(monkeypatch):
    """P1: data-URI budget per artifact — marker2 vượt budget → GIỮ marker (không embed) + warning;
    marker1 (trong budget) vẫn embed."""
    import app.services.render_md as rm

    rid1, rid2 = "p1_b1", "p1_b2"
    m1 = IMAGE_MARKER.format(region_id=rid1)
    m2 = IMAGE_MARKER.format(region_id=rid2)
    png = b"\x89PNG\r\n\x1a\nfake"
    per = len(base64.b64encode(png))  # b64 bytes/ảnh
    monkeypatch.setattr(rm, "MAX_DATA_URI_BYTES", per)  # budget vừa đúng 1 ảnh

    async def _loader(rid: str) -> bytes:
        return png

    out = await embed_crop_keys(f"{m1}\n\n{m2}", 7, _FakeStorage(set()), crop_loader=_loader)
    b64 = base64.b64encode(png).decode("ascii")
    # marker1 embed, marker2 vượt budget → giữ nguyên marker
    assert out == f"![vùng {rid1}](data:image/png;base64,{b64})\n\n{m2}"

async def test_embed_crop_keys_ondemand_fail_keeps_marker():
    """On-demand crop lỗi (region/bbox/original thiếu) → giữ marker (không crash)."""
    async def _loader(rid: str) -> bytes:
        raise KeyError(rid)

    out = await embed_crop_keys(MARKER, 7, _FakeStorage(set()), crop_loader=_loader)
    assert out == MARKER

async def test_embed_crop_keys_exists_wins_over_loader():
    """Crop artifact đã ingest → relative key (như cũ), loader KHÔNG được gọi."""
    called = []

    async def _loader(rid: str) -> bytes:
        called.append(rid)
        return b"\x89PNG\r\n\x1a\nx"

    out = await embed_crop_keys(MARKER, 7, _FakeStorage({KEY}), crop_loader=_loader)
    assert out == f"![vùng {RID}](crops/{RID}.png)"
    assert called == []

async def test_embed_crop_urls_relative_key_to_presigned():
    """serve/download: relative key → presigned 24h FRESH tại serve-time."""
    md = f"chào\n\n![vùng {RID}](crops/{RID}.png)\n\nhết"
    out = await embed_crop_urls(md, 7, _FakeStorage({KEY}))
    assert f"![vùng {RID}](https://cdn.example/{KEY}?sig=abc)" in out


async def test_embed_crop_keys_missing_crop_keeps_marker():
    md = f"a\n\n{MARKER}"
    out = await embed_crop_urls(md, 7, _FakeStorage(set()))
    assert out == md  # nguyên vẹn, không thay


async def test_embed_crop_urls_no_key_untouched():
    md = "# thuần văn bản"
    assert await embed_crop_urls(md, 7, _FakeStorage({KEY})) == md


def test_html_to_docx_embeds_crop_bytes():
    html = f'<p>trước</p><img src="crops/{RID}.png"/><p>sau</p>'
    data = html_to_docx(html, crops={RID: _PNG_BYTES})
    doc = Document(io.BytesIO(data))
    assert [p.text for p in doc.paragraphs if p.text] == ["trước", "sau"]
    assert len(doc.inline_shapes) == 1  # ảnh được embed


def test_html_to_docx_img_without_crop_dropped():
    data = html_to_docx(f'<p>x</p><img src="crops/{RID}.png"/>', crops={})
    doc = Document(io.BytesIO(data))
    assert len(doc.inline_shapes) == 0  # crop thiếu → drop như cũ
    assert doc.paragraphs[0].text == "x"


def test_html_to_docx_presigned_url_src_parses_rid():
    html = f'<img src="https://cdn.example/exports/7/crops/{RID}.png?sig=q"/>'
    data = html_to_docx(html, crops={RID: _PNG_BYTES})
    assert len(Document(io.BytesIO(data)).inline_shapes) == 1


_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000"
    "0049454e44ae426082"
)

def test_html_to_docx_invalid_crop_bytes_dropped_not_500():
    """add_picture(bytes hỏng) raise → wrap: drop img như crop thiếu."""
    html = f'<p>trước</p><img src="crops/{RID}.png"/><p>sau</p>'
    data = html_to_docx(html, crops={RID: b"not-a-png"})
    doc = Document(io.BytesIO(data))
    assert len(doc.inline_shapes) == 0
    assert [p.text for p in doc.paragraphs if p.text] == ["trước", "sau"]
