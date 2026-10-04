"""Task 2: POST /api/jobs — upload endpoint tests (brief Task 2 Step 1)."""

import io

from PIL import Image
from pypdf import PdfWriter

from app.models import Job

def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
    return buf.getvalue()

def _pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

TEST_JPEG = _jpeg_bytes()
TEST_PDF_3 = _pdf_bytes(3)
TEST_PDF_51 = _pdf_bytes(51)

async def test_upload_image_201(auth_client, storage_spy):
    r = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 201 and r.json()["page_count"] == 1 and r.json()["file_type"] == "image"

async def test_upload_pdf_3_pages(auth_client):
    r = await auth_client.post("/api/jobs", files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")})
    assert r.json()["page_count"] == 3

async def test_upload_pdf_51_pages_422_no_storage(auth_client, storage_spy):
    r = await auth_client.post("/api/jobs", files={"file": ("big.pdf", TEST_PDF_51, "application/pdf")})
    assert r.status_code == 422 and "50 trang" in r.json()["detail"]
    assert storage_spy.put.call_count == 0

async def test_upload_corrupt_pdf_422_no_storage(auth_client, storage_spy):
    """Malformed PDF bytes → synchronous 422, no storage write (spec §6)."""
    r = await auth_client.post("/api/jobs", files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and r.json()["detail"] == "File PDF không hợp lệ."
    assert storage_spy.put.call_count == 0

async def test_upload_over_size_cap_422(auth_client, storage_spy, monkeypatch):
    import app.routers.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "MAX_UPLOAD_BYTES", 1024)
    r = await auth_client.post("/api/jobs", files={"file": ("big.jpg", b"x" * 2048, "image/jpeg")})
    assert r.status_code == 422 and "50MB" in r.json()["detail"]
    assert storage_spy.put.call_count == 0

async def test_upload_bad_type_422(auth_client):
    r = await auth_client.post("/api/jobs", files={"file": ("a.gif", b"RIFF", "image/gif")})
    assert r.status_code == 422

async def test_upload_requires_ocr_enabled(client):
    await client.post("/api/auth/register", json={"email": "e@x.io", "password": "secret123"})
    r = await client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 403

async def test_upload_daily_limit_429(auth_client):
    for _ in range(20):
        await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    r = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 429

async def test_dedupe_same_content(auth_client, db_session):
    r1 = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    r2 = await auth_client.post("/api/jobs", files={"file": ("b.jpg", TEST_JPEG, "image/jpeg")})
    j1 = await db_session.get(Job, r1.json()["id"]); j2 = await db_session.get(Job, r2.json()["id"])
    assert j1.storage_key == j2.storage_key and j1.id != j2.id
