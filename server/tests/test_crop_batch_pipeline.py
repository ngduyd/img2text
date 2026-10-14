"""Lane K Task3 — integration: kernel crop → S3 → embed (đường chính).

Mock storage + kernel output file `{job_id}_crop_{rid}.png`:
`_ingest_batch_crops` put `exports/{job_id}/crops/{rid}.png` →
`embed_crop_keys` render `![vùng {rid}](crops/{rid}.png)` (relative key,
KHÔNG data-URI, KHÔNG on-demand) → `embed_crop_urls` serve presigned cùng key.
"""

from pathlib import Path

from app.core.schemas import IMAGE_MARKER
from app.services.render_md import embed_crop_keys, embed_crop_urls

JOB_ID = 7
RID = "p1_b15"
KEY = f"exports/{JOB_ID}/crops/{RID}.png"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc000000301010018dd8db0000000"
    "0049454e44ae426082"
)

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

    async def presign_get(self, key: str, expires: int) -> str:
        assert key in self.data, key
        return f"https://cdn.example/{key}?sig=abc"

async def test_kernel_crop_s3_embed_roundtrip(tmp_path, monkeypatch):
    import app.services.kaggle_orchestrator as orch

    st = _MemStorage()
    monkeypatch.setattr(orch, "_get_storage", lambda: st)

    # kernel output (mock): {job_id}_crop_{rid}.png trong out_dir
    (tmp_path / f"{JOB_ID}_crop_{RID}.png").write_bytes(PNG)
    (tmp_path / f"{JOB_ID}_result.json").write_text("{}")
    (tmp_path / "99_crop_other.png").write_bytes(PNG)  # job khác không ingest
    await orch._ingest_batch_crops(JOB_ID, tmp_path)

    assert set(st.data) == {KEY}  # đúng key, không tràn job khác
    assert st.data[KEY] == PNG

    # render: marker → relative key, loader (on-demand) KHÔNG được gọi
    async def _no_loader(rid: str) -> bytes:
        raise AssertionError("batch crop có → on-demand không được gọi")

    marker = IMAGE_MARKER.format(region_id=RID)
    md = await embed_crop_keys(marker, JOB_ID, st, crop_loader=_no_loader)
    assert md == f"![vùng {RID}](crops/{RID}.png)"
    assert "data:" not in md and "http" not in md

    # serve: relative key → presigned cùng S3 key batch
    served = await embed_crop_urls(md, JOB_ID, st)
    assert served == f"![vùng {RID}](https://cdn.example/{KEY}?sig=abc)"

async def test_embed_falls_back_to_ondemand_when_batch_missing():
    """Batch thiếu → on-demand data-URI (fallback đường phụ không đứt)."""
    st = _MemStorage()
    marker = IMAGE_MARKER.format(region_id=RID)

    async def _loader(rid: str) -> bytes:
        return PNG

    md = await embed_crop_keys(marker, JOB_ID, st, crop_loader=_loader)
    assert md.startswith(f"![vùng {RID}](data:image/png;base64,")
