"""Plan D Task 3: html/docx export via pandoc + reference.docx (brief tests verbatim)."""

import io
import zipfile

import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.models import Job, User

async def test_export_docx_bytes_valid(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_result}/docx")
    assert body[:2] == b"PK"                                    # zip container
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert "word/document.xml" in z.namelist()

async def test_export_html_contains_heading(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "html"})
    body = (await storage.get(f"exports/{done_job_with_result}/html")).decode()
    assert "<h2" in body

async def test_export_uses_reference_styles(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_result}/docx")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        styles = z.read("word/styles.xml").decode()
    assert "Heading1" in styles and "Calibri" in styles          # reference.docx applied


@pytest_asyncio.fixture
async def done_job_with_marker_crop(auth_client, db_session, storage) -> int:
    """Done job: image_unextractable region WITH bbox + marker in markdown;
    original seeded in R2 (crop embed test, brief Task 3 extra)."""
    marker = "**[Hình ảnh chưa trích xuất: vùng r1]**"
    result = {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 12.5,
        "warnings": [],
        "markdown": f"# tài liệu\n\n{marker}",
        "pages": [
            {
                "index": 0,
                "width": 200,
                "height": 400,
                "page_flag": "ok",
                "markdown": f"# tài liệu\n\n{marker}",
                "regions": [
                    {
                        "id": "r1",
                        "bbox": [100, 50, 200, 150],
                        "text": "",
                        "verdict": "image_unextractable",
                        "placeholder": True,
                    }
                ],
            }
        ],
    }
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=result,
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    img = Image.new("RGB", (200, 400), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    await storage.put("uploads/test.jpg", buf.getvalue())
    return job.id

async def test_export_docx_embeds_materialized_crop(
    auth_client, done_job_with_marker_crop, storage
):
    """Crop embedded: docx zip contains word/media/ file (marker rewritten)."""
    await auth_client.post(
        f"/api/jobs/{done_job_with_marker_crop}/export", json={"fmt": "docx"}
    )
    body = await storage.get(f"exports/{done_job_with_marker_crop}/docx")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert any(n.startswith("word/media/") for n in z.namelist())
