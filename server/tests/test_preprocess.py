"""Task 1 (Plan W): job preprocess — page selection + rotation metadata."""

import io
import json

from pypdf import PdfWriter
from sqlalchemy import select

from app.models import Job
from tests.conftest import PNG_1PX

def _pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

TEST_PDF_3 = _pdf_bytes(3)

async def test_preprocess_roundtrip(auth_client, worker_client, db_session):
    """Valid preprocess stored as TEXT on Job; /jobs/next returns parsed dict."""
    preprocess = {"pages": [1, 3], "rotate": {"3": 90}}
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")},
        data={"preprocess": json.dumps(preprocess)},
    )
    assert r.status_code == 201, r.text
    job = (
        await db_session.execute(select(Job).where(Job.id == r.json()["id"]))
    ).scalar_one()
    assert json.loads(job.preprocess) == preprocess
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200, r.text
    assert r.json()["preprocess"] == preprocess

async def test_preprocess_empty_pages_422(auth_client, storage_spy):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")},
        data={"preprocess": json.dumps({"pages": [], "rotate": {}})},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Chưa chọn trang nào."
    assert storage_spy.put.call_count == 0

async def test_preprocess_page_out_of_range_422(auth_client, storage_spy):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")},
        data={"preprocess": json.dumps({"pages": [99], "rotate": {}})},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Trang chọn vượt quá số trang của file."
    assert storage_spy.put.call_count == 0

async def test_preprocess_rotate_key_not_selected_422(auth_client, storage_spy):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")},
        data={"preprocess": json.dumps({"pages": [1], "rotate": {"2": 90}})},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Xoay áp dụng cho trang đã chọn."
    assert storage_spy.put.call_count == 0

async def test_preprocess_rotate_value_invalid_422(auth_client, storage_spy):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")},
        data={"preprocess": json.dumps({"pages": [1], "rotate": {"1": 45}})},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Góc xoay không hợp lệ."
    assert storage_spy.put.call_count == 0

async def test_preprocess_image_422(auth_client, storage_spy):
    """Non-null preprocess on image upload → PDF-only error."""
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.png", PNG_1PX, "image/png")},
        data={"preprocess": json.dumps({"pages": [1], "rotate": {}})},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Chỉ file PDF hỗ trợ chọn trang."
    assert storage_spy.put.call_count == 0

async def test_preprocess_absent_null(auth_client, worker_client):
    """No preprocess field → job.preprocess stays null; payload null."""
    r = await auth_client.post(
        "/api/jobs", files={"file": ("a.png", PNG_1PX, "image/png")}
    )
    assert r.status_code == 201, r.text
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200, r.text
    assert r.json()["preprocess"] is None
