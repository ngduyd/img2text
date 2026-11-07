"""Crop cho job PDF: rasterize trang bằng PyMuPDF rồi cắt bbox.

Ruling R26 cũ ("PDF jobs have no PIL-decodable original") làm mọi vùng ảnh
của job PDF chỉ còn marker text trong md-layout lẫn docx-layout. PyMuPDF đã
là dependency của server → tự cắt được, không cần Kaggle kernel.
"""

import io

import pytest
from types import SimpleNamespace

from app.routers import exports as exports_mod
from app.services.storage import get_storage


class _MemStorage:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.data[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self.data:
            raise KeyError(key)
        return self.data[key]

    async def exists(self, key: str) -> bool:
        return key in self.data


def _one_page_pdf(width: int = 200, height: int = 400) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(10, 20, 60, 80), color=(1, 0, 0), fill=(1, 0, 0))
    data = doc.tobytes()
    doc.close()
    return data


def _job(pdf: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        file_type="pdf",
        storage_key="uploads/x.pdf",
        result={
            "pages": [{
                "index": 1, "width": 200, "height": 400, "page_flag": "ok",
                "regions": [{
                    "id": "p1r0", "bbox": [10, 20, 60, 80], "text": "",
                    "verdict": "image_unextractable", "placeholder": True,
                }],
            }],
        },
        layout_style=None,
    )


@pytest.mark.nodb
async def test_pdf_region_crop_is_generated(monkeypatch):
    pdf = _one_page_pdf()
    job = _job(pdf)
    storage = _MemStorage()
    await storage.put("uploads/x.pdf", pdf)

    key = await exports_mod.get_or_make_crop(
        7, "p1r0", job, job.result, storage
    )
    data = await storage.get(key)
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    # bbox 50x60 px trang 200x400 → crop đúng tỉ lệ (không phải ảnh full trang)
    assert 40 <= img.width <= 60
    assert 50 <= img.height <= 70


@pytest.mark.nodb
async def test_pdf_page_missing_raises_keyerror(monkeypatch):
    job = _job(_one_page_pdf())
    job.result["pages"][0]["index"] = 9  # trang không tồn tại
    storage = _MemStorage()
    await storage.put("uploads/x.pdf", job.storage_key and _one_page_pdf())
    with pytest.raises(KeyError):
        await exports_mod.get_or_make_crop(7, "p1r0", job, job.result, storage)
