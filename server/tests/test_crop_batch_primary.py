"""Lane K — batch crop (kernel PNG) là nguồn chính; server chỉ LƯỮ + DÙNG.

- `_materialize_crops` PHẢI đọc crop kernel đã ingest
  `exports/{job_id}/crops/{rid}.png` trước; on-demand jpg
  (`get_or_make_crop` → `crops/{job_id}/{rid}.jpg`) chỉ fallback khi batch
  crop thiếu.
- `_embed_crops_as_data_uris` (html/pdf) PHẢI nuốt cả ref .jpg lẫn .png.
"""

from types import SimpleNamespace

from app.core.schemas import IMAGE_MARKER
from app.routers import exports as exports_mod
from app.routers.exports import _embed_crops_as_data_uris, _materialize_crops

RID = "p1_b15"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000"
    "0049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xfake-jpeg"

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

def _job() -> SimpleNamespace:
    return SimpleNamespace(
        result={
            "pages": [{
                "index": 0, "width": 200, "height": 400, "page_flag": "ok",
                "regions": [{
                    "id": RID, "bbox": [0, 0, 10, 10], "text": "",
                    "verdict": "image_unextractable", "placeholder": True,
                }],
            }],
        },
        storage_key="uploads/x.jpg",
    )

def _marker() -> str:
    return IMAGE_MARKER.format(region_id=RID)

async def test_materialize_crops_batch_png_wins(tmp_path, monkeypatch):
    """Batch crop đã ingest → DÙNG thẳng PNG; on-demand get_or_make_crop
    KHÔNG được chạy (server không cắt lại)."""
    st = _MemStorage()
    await st.put(f"exports/7/crops/{RID}.png", PNG)

    async def _boom(*args, **kwargs):
        raise AssertionError("batch crop có → on-demand không được gọi")

    monkeypatch.setattr(exports_mod, "get_or_make_crop", _boom)
    md = await _materialize_crops(7, _marker(), _job(), st, tmp_path)
    assert md == f"![vùng {RID}](crops/{RID}.png)"
    assert (tmp_path / "crops" / f"{RID}.png").read_bytes() == PNG

async def test_materialize_crops_falls_back_to_ondemand_jpg(tmp_path, monkeypatch):
    """Batch crop THIẾU → fallback on-demand jpg (hành vi cũ giữ nguyên)."""
    st = _MemStorage()
    await st.put(f"crops/7/{RID}.jpg", JPEG)

    async def _make(job_id, rid, job, result, storage):
        assert rid == RID
        return f"crops/{job_id}/{rid}.jpg"

    monkeypatch.setattr(exports_mod, "get_or_make_crop", _make)
    md = await _materialize_crops(7, _marker(), _job(), st, tmp_path)
    assert md == f"![vùng {RID}](crops/{RID}.jpg)"
    assert (tmp_path / "crops" / f"{RID}.jpg").read_bytes() == JPEG

async def test_materialize_crops_batch_missing_keeps_marker(tmp_path, monkeypatch):
    """Batch THIẾU + on-demand KeyError (region/original thiếu) → giữ marker."""
    st = _MemStorage()

    async def _miss(job_id, rid, job, result, storage):
        raise KeyError(rid)

    monkeypatch.setattr(exports_mod, "get_or_make_crop", _miss)
    md = await _materialize_crops(7, _marker(), _job(), st, tmp_path)
    assert md == _marker()

def test_embed_crops_as_data_uris_handles_png(tmp_path):
    """html/pdf export: ref crops/{rid}.png (batch path) → data:image/png;
    chỉ nuốt .jpg là crop batch rơi khỏi data-URI → img 404 khi mở html."""
    (tmp_path / "crops").mkdir()
    (tmp_path / "crops" / f"{RID}.png").write_bytes(PNG)
    html = f'<p><img src="crops/{RID}.png" alt="x" /></p>'
    out = _embed_crops_as_data_uris(html, tmp_path)
    assert f'src="data:image/png;base64,' in out
    assert 'src="crops/' not in out

def test_embed_crops_as_data_uris_keeps_jpg(tmp_path):
    (tmp_path / "crops").mkdir()
    (tmp_path / "crops" / f"{RID}.jpg").write_bytes(JPEG)
    html = f'<p><img src="crops/{RID}.jpg" alt="x" /></p>'
    out = _embed_crops_as_data_uris(html, tmp_path)
    assert 'src="data:image/jpeg;base64,' in out
    assert 'src="crops/' not in out

def test_embed_crops_as_data_uris_missing_crop_keeps_ref(tmp_path):
    (tmp_path / "crops").mkdir()
    html = f'<p><img src="crops/{RID}.png" /></p>'
    assert _embed_crops_as_data_uris(html, tmp_path) == html
