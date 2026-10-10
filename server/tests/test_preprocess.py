"""Task 1 (Plan W): job preprocess — page selection + rotation metadata.

R2 flow: preprocess rides the metadata POST /api/jobs body (object, not a
multipart JSON string). A create-side 422 happens AFTER the browser upload,
so the invariant asserted here is "no job row", not "no storage write"."""

import json

from sqlalchemy import func, select

from app.core.models import Job
from tests.conftest import PNG_1PX, TEST_PDF_3

async def _no_job_rows(db_session) -> bool:
    count = (
        await db_session.execute(select(func.count()).select_from(Job))
    ).scalar_one()
    return count == 0

async def test_preprocess_roundtrip(upload, worker_client, db_session):
    """Valid preprocess stored as TEXT on Job; /jobs/next returns parsed dict."""
    preprocess = {"pages": [1, 3], "rotate": {"3": 90}}
    r = await upload(TEST_PDF_3, "a.pdf", preprocess=preprocess)
    assert r.status_code == 201, r.text
    job = (
        await db_session.execute(select(Job).where(Job.id == r.json()["id"]))
    ).scalar_one()
    assert json.loads(job.preprocess) == preprocess
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200, r.text
    assert r.json()["preprocess"] == preprocess

async def test_preprocess_empty_pages_422(upload, db_session):
    r = await upload(
        TEST_PDF_3, "a.pdf", preprocess={"pages": [], "rotate": {}}
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Chưa chọn trang nào."
    assert await _no_job_rows(db_session)

async def test_preprocess_page_out_of_range_422(upload, db_session):
    r = await upload(
        TEST_PDF_3, "a.pdf", preprocess={"pages": [99], "rotate": {}}
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Trang chọn vượt quá số trang của file."
    assert await _no_job_rows(db_session)

async def test_preprocess_rotate_key_not_selected_422(upload, db_session):
    r = await upload(
        TEST_PDF_3, "a.pdf", preprocess={"pages": [1], "rotate": {"2": 90}}
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Xoay áp dụng cho trang đã chọn."
    assert await _no_job_rows(db_session)

async def test_preprocess_rotate_value_invalid_422(upload, db_session):
    r = await upload(
        TEST_PDF_3, "a.pdf", preprocess={"pages": [1], "rotate": {"1": 45}}
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Góc xoay không hợp lệ."
    assert await _no_job_rows(db_session)

async def test_preprocess_image_422(upload, db_session):
    """Non-null preprocess on image upload → PDF-only error."""
    r = await upload(PNG_1PX, "a.png", preprocess={"pages": [1], "rotate": {}})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Chỉ file PDF hỗ trợ chọn trang."
    assert await _no_job_rows(db_session)

async def test_preprocess_absent_null(upload, worker_client):
    """No preprocess field → job.preprocess stays null; payload null."""
    r = await upload(PNG_1PX, "a.png")
    assert r.status_code == 201, r.text
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200, r.text
    assert r.json()["preprocess"] is None
