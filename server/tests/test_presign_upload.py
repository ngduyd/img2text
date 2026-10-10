"""F2 (spec 2026-10-10): POST /api/jobs/presign sanity + policy, and
metadata-only POST /api/jobs (head-verify 404). The multipart UploadFile
path is removed — bytes go browser → storage directly."""

import hashlib
from unittest.mock import AsyncMock

from app.core.models import Job
from app.routers.jobs import MAX_PDF_PAGES
from tests.conftest import PNG_1PX, TEST_JPEG, TEST_PDF_3, upload_job

MAX_BYTES = 50 * 1024 * 1024

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _presign_body(data: bytes = PNG_1PX, filename: str = "t.png", **over):
    ext = filename.rsplit(".", 1)[-1].lower()
    body = {
        "filename": filename,
        "content_type": {
            "png": "image/png",
            "jpg": "image/jpeg",
            "pdf": "application/pdf",
        }.get(ext, "application/octet-stream"),
        "size_bytes": len(data),
        "sha256": _sha(data),
    }
    body.update(over)
    return body

# --- presign: sanity checks + policy ---

async def test_presign_ok_returns_content_addressed_policy(auth_client):
    r = await auth_client.post("/api/jobs/presign", json=_presign_body())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["storage_key"] == f"uploads/{_sha(PNG_1PX)}.png"
    assert out["max_bytes"] == MAX_BYTES
    assert out["fields"]["key"] == out["storage_key"]
    assert out["fields"]["Content-Type"] == "image/png"
    assert out["url"].startswith("http")

async def test_presign_rejects_oversize(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(size_bytes=MAX_BYTES + 1)
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "File vượt quá 50MB."

async def test_presign_rejects_bad_extension(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(filename="a.gif")
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Định dạng file không được hỗ trợ."

async def test_presign_rejects_page_over_cap(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign",
        json=_presign_body(
            data=TEST_PDF_3, filename="a.pdf", page_count=MAX_PDF_PAGES + 1
        ),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == f"File PDF quá {MAX_PDF_PAGES} trang."

async def test_presign_page_count_optional(auth_client):
    """UI uploads FIRST (progress bar) and counts pages after with pdf.js —
    page bound then enforced at POST /api/jobs."""
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(data=TEST_PDF_3, filename="a.pdf")
    )
    assert r.status_code == 200, r.text

async def test_presign_image_page_count_must_be_1(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(page_count=2)
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Số trang không hợp lệ."

async def test_presign_rejects_bad_sha256(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(sha256="deadbeef")
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "sha256 không hợp lệ."

async def test_presign_rejects_invalid_output_format(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(output_format="pdf")
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Đầu ra không hợp lệ."

async def test_presign_rejects_invalid_mode(auth_client):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body(mode="pdf")
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Chế độ xử lý không hợp lệ."

async def test_presign_requires_ocr_enabled(client):
    await client.post(
        "/api/auth/register", json={"email": "e@x.io", "password": "secret123"}
    )
    r = await client.post("/api/jobs/presign", json=_presign_body())
    assert r.status_code == 403

async def test_presign_failure_is_500(app, auth_client, monkeypatch):
    """presign_post fail (storage down) → 500, never a signed policy."""
    monkeypatch.setattr(
        app.state.storage,
        "presign_post",
        AsyncMock(side_effect=RuntimeError("s3 down")),
    )
    r = await auth_client.post("/api/jobs/presign", json=_presign_body())
    assert r.status_code == 500

# --- create: metadata-only + head verify ---

async def test_create_image_201_metadata(upload):
    r = await upload(PNG_1PX, "t.png")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "queued"
    assert out["page_count"] == 1 and out["file_type"] == "image"
    assert out["output_format"] == "md" and out["mode"] == "layout"

async def test_create_pdf_metadata(upload):
    r = await upload(TEST_PDF_3, "a.pdf")
    assert r.status_code == 201, r.text
    assert r.json()["page_count"] == 3 and r.json()["file_type"] == "pdf"

async def test_create_missing_upload_404(auth_client):
    key = f"uploads/{'a' * 64}.png"  # valid shape, never uploaded
    r = await auth_client.post(
        "/api/jobs", json={"storage_key": key, "page_count": 1}
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "File chưa tải lên."

async def test_create_rejects_bad_storage_key(auth_client):
    for key in ("uploads/x.png", "../../etc/passwd", f"uploads/{'A' * 64}.png"):
        r = await auth_client.post(
            "/api/jobs", json={"storage_key": key, "page_count": 1}
        )
        assert r.status_code == 422, key
        assert r.json()["detail"] == "Đường dẫn file không hợp lệ."

async def test_create_page_over_cap_422(auth_client, app):
    r = await auth_client.post(
        "/api/jobs/presign",
        json=_presign_body(data=TEST_PDF_3, filename="a.pdf"),
    )
    key = r.json()["storage_key"]
    await app.state.storage.put(key, TEST_PDF_3)
    r = await auth_client.post(
        "/api/jobs",
        json={"storage_key": key, "page_count": MAX_PDF_PAGES + 1},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == f"File PDF quá {MAX_PDF_PAGES} trang."

async def test_create_image_page_count_not_one_422(auth_client, app):
    r = await auth_client.post(
        "/api/jobs/presign", json=_presign_body()
    )
    key = r.json()["storage_key"]
    await app.state.storage.put(key, PNG_1PX)
    r = await auth_client.post(
        "/api/jobs", json={"storage_key": key, "page_count": 3}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Số trang không hợp lệ."

async def test_create_daily_limit_429(upload):
    for _ in range(20):
        r = await upload(PNG_1PX, "t.png")
        assert r.status_code == 201, r.text
    r = await upload(PNG_1PX, "t.png")
    assert r.status_code == 429

async def test_create_dedupe_same_content(auth_client, app, db_session):
    """Content-addressed key: same bytes → same storage_key, distinct jobs."""
    r1 = await upload_job(
        auth_client, app.state.storage, TEST_JPEG, "a.jpg"
    )
    r2 = await upload_job(
        auth_client, app.state.storage, TEST_JPEG, "b.jpg"
    )
    assert r1.json()["id"] != r2.json()["id"]
    j1 = await db_session.get(Job, r1.json()["id"])
    j2 = await db_session.get(Job, r2.json()["id"])
    assert j1.storage_key == j2.storage_key
