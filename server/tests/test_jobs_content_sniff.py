"""Create-time magic-byte sniff (spec 2026-10-13 §9b): metadata
(content_type) là primary, sniff bytes là cross-check chặn file sai đuôi
thật sự (Version 20: '.jpg' thật ra là '%PDF-1.7' → kernel
'cannot identify image file'). Mismatch → 422 rõ ràng + delete object."""

from app.core.models import Job
from sqlalchemy import func, select

from tests.conftest import TEST_JPEG, TEST_PDF_3  # noqa: F401


async def test_create_pdf_bytes_named_jpg_422_and_object_deleted(
    upload, storage_spy, db_session
):
    r = await upload(TEST_PDF_3, "fake.jpg")
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "File (.jpg) không khớp nội dung file (pdf thật)"
    )
    deleted = [c.args[0] for c in storage_spy.delete_prefix.await_args_list]
    assert any(k.startswith("uploads/") and k.endswith(".jpg") for k in deleted), \
        "object content-addressed phải bị xóa sau 422"
    n = (await db_session.execute(select(func.count(Job.id)))).scalar_one()
    assert n == 0  # không insert row cho file sai nội dung


async def test_create_real_jpg_still_201(upload, db_session):
    """Cross-check không false-positive: jpg thật tên .jpg → 201 (sniff pass)."""
    r = await upload(TEST_JPEG, "real.jpg")
    assert r.status_code == 201, r.text
