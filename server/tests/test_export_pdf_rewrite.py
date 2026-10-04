"""Plan D Task 4: pdf export + marker→image rewrite in all formats + html sanitize."""

import io
import zipfile

import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.models import Job, User


async def _done_job(db_session, storage, markdown: str, regions: list) -> int:
    """Done job seeded directly; original 200x400 JPEG in R2."""
    result = {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 12.5,
        "warnings": [],
        "markdown": markdown,
        "pages": [
            {
                "index": 0,
                "width": 200,
                "height": 400,
                "page_flag": "ok",
                "markdown": markdown,
                "regions": regions,
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
    buf = io.BytesIO()
    Image.new("RGB", (200, 400), "red").save(buf, format="JPEG")
    await storage.put("uploads/test.jpg", buf.getvalue())
    return job.id


@pytest_asyncio.fixture
async def done_job_with_marker_and_crop(auth_client, db_session, storage) -> int:
    """Region p1r0 image_unextractable WITH bbox; marker in markdown."""
    return await _done_job(
        db_session,
        storage,
        "# tài liệu\n\n**[Hình ảnh chưa trích xuất: vùng p1r0]**",
        [
            {
                "id": "p1r0",
                "bbox": [100, 50, 200, 150],
                "text": "",
                "verdict": "image_unextractable",
                "placeholder": True,
            }
        ],
    )


@pytest_asyncio.fixture
async def done_job_with_null_bbox_marker(auth_client, db_session, storage) -> int:
    """Region p1r1 image_unextractable WITH bbox None; marker must survive."""
    return await _done_job(
        db_session,
        storage,
        "# tài liệu\n\n**[Hình ảnh chưa trích xuất: vùng p1r1]**",
        [
            {
                "id": "p1r1",
                "bbox": None,
                "text": "",
                "verdict": "image_unextractable",
                "placeholder": True,
            }
        ],
    )


@pytest_asyncio.fixture
async def done_job_with_xss(auth_client, db_session, storage) -> int:
    """Markdown containing a raw script tag (must never be executable in html)."""
    return await _done_job(
        db_session,
        storage,
        "# tài liệu\n\n<script>alert(1)</script>\n\nnội dung",
        [],
    )


async def test_export_pdf_magic(auth_client, done_job_with_result, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_result}/export", json={"fmt": "pdf"})
    body = await storage.get(f"exports/{done_job_with_result}/pdf")
    assert body[:4] == b"%PDF"


async def test_image_regions_embedded_in_exports(auth_client, done_job_with_marker_and_crop, storage):
    # result has image_unextractable region p1r0 with bbox + crop already in R2
    await auth_client.post(f"/api/jobs/{done_job_with_marker_and_crop}/export", json={"fmt": "md"})
    md = (await storage.get(f"exports/{done_job_with_marker_and_crop}/md")).decode()
    assert "![vùng p1r0](crops/p1r0.jpg)" in md
    assert "**[Hình ảnh chưa trích xuất: vùng p1r0]**" not in md
    await auth_client.post(f"/api/jobs/{done_job_with_marker_and_crop}/export", json={"fmt": "docx"})
    body = await storage.get(f"exports/{done_job_with_marker_and_crop}/docx")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert any(n.startswith("word/media/") for n in z.namelist())


async def test_null_bbox_keeps_marker(auth_client, done_job_with_null_bbox_marker, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_null_bbox_marker}/export", json={"fmt": "md"})
    md = (await storage.get(f"exports/{done_job_with_null_bbox_marker}/md")).decode()
    assert "**[Hình ảnh chưa trích xuất: vùng p1r1]**" in md


async def test_script_in_markdown_not_executable_in_html(auth_client, done_job_with_xss, storage):
    await auth_client.post(f"/api/jobs/{done_job_with_xss}/export", json={"fmt": "html"})
    body = (await storage.get(f"exports/{done_job_with_xss}/html")).decode()
    assert "<script>alert(1)</script>" not in body
