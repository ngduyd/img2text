"""WS-PIPE task 4: render embed crop artifact.

md: marker → `![vùng {rid}]({presigned 24h})` khi storage có
exports/{id}/crops/{rid}.png (không có → giữ marker).
docx: html_to_docx img node → embed bytes crop trực tiếp (không phụ thuộc
URL); crop thiếu → img bị drop như cũ (không crash)."""

import io

from docx import Document

from app.core.schemas import IMAGE_MARKER
from app.services.html_to_docx import html_to_docx
from app.services.render_md import embed_crop_urls

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


async def test_embed_crop_urls_marker_to_presigned():
    md = f"chào\n\n{MARKER}\n\nhết"
    out = await embed_crop_urls(md, 7, _FakeStorage({KEY}))
    assert f"![vùng {RID}](https://cdn.example/{KEY}?sig=abc)" in out
    assert MARKER not in out


async def test_embed_crop_urls_missing_crop_keeps_marker():
    md = f"a\n\n{MARKER}"
    out = await embed_crop_urls(md, 7, _FakeStorage(set()))
    assert out == md  # nguyên vẹn, không thay


async def test_embed_crop_urls_no_marker_untouched():
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
