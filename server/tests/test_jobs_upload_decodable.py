"""File ảnh hỏng/cụt phải bị chặn NGAY lúc tạo job (422), không để kernel
chết sau vài phút với "broken data stream when reading image file".

Bug thật (job 80/81/83): object uploads/a4bcd7…png chỉ có 70 byte — đúng chữ
ký PNG nên qua được magic-byte sniff, nhưng không decode được → 29 job failed.
"""

import io

from PIL import Image
from sqlalchemy import func, select

from app.core.models import Job

PNG_HEAD_ONLY = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
)


def _valid_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


async def test_truncated_png_422_and_no_row(upload, db_session, storage_spy):
    r = await upload(PNG_HEAD_ONLY, "bang-luong.png")
    assert r.status_code == 422, r.text
    assert "không đọc được" in r.json()["detail"]
    n = (await db_session.execute(select(func.count(Job.id)))).scalar_one()
    assert n == 0
    deleted = [c.args[0] for c in storage_spy.delete_prefix.await_args_list]
    assert any(k.startswith("uploads/") and k.endswith(".png") for k in deleted)


async def test_valid_png_201(upload, db_session):
    r = await upload(_valid_png(), "bang-luong.png")
    assert r.status_code == 201, r.text
    n = (await db_session.execute(select(func.count(Job.id)))).scalar_one()
    assert n == 1
