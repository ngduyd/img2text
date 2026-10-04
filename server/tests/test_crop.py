"""Plan D Task 2: lazy region crops (brief tests verbatim)."""

import io

import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.models import Job, User
from tests.test_jobs_read import other_client  # noqa: F401

ORIGINAL_KEY = "uploads/test.jpg"

def _original_jpeg() -> bytes:
    """200x400: left half red, right half blue (brief spec)."""
    img = Image.new("RGB", (200, 400))
    img.paste("red", (0, 0, 100, 400))
    img.paste("blue", (100, 0, 200, 400))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

def _result(bbox) -> dict:
    return {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 12.5,
        "warnings": [],
        "markdown": "# tài liệu",
        "pages": [
            {
                "index": 0,
                "width": 200,
                "height": 400,
                "page_flag": "ok",
                "markdown": "# tài liệu",
                "regions": [
                    {
                        "id": "p1r0",
                        "bbox": bbox,
                        "text": "Xin chào",
                        "verdict": "ok",
                        "placeholder": False,
                    }
                ],
            }
        ],
    }

async def _seed_done_job(db_session, storage, bbox) -> int:
    """Done job for auth_client user; original JPEG seeded under storage_key."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=_result(bbox),
        storage_key=ORIGINAL_KEY,
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    await storage.put(ORIGINAL_KEY, _original_jpeg())
    return job.id

@pytest_asyncio.fixture
async def done_job_with_bbox(auth_client, db_session, storage) -> int:
    """Done job, region p1r0 bbox [100, 50, 200, 150], original in R2."""
    return await _seed_done_job(db_session, storage, [100, 50, 200, 150])

@pytest_asyncio.fixture
async def done_job_with_null_bbox(auth_client, db_session, storage) -> int:
    """Done job, region p1r0 bbox None."""
    return await _seed_done_job(db_session, storage, None)

async def test_crop_generated_and_cached(auth_client, done_job_with_bbox, storage_spy, storage):
    r = await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")
    assert r.status_code == 200 and "crops/" in r.json()["url"]
    n = storage_spy.put.call_count
    await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")  # cache hit
    assert storage_spy.put.call_count == n
    img = Image.open(io.BytesIO(await storage.get(f"crops/{done_job_with_bbox}/p1r0.jpg")))
    assert img.width == 100 and 95 <= img.height <= 105          # resized ≤800, bbox size

async def test_crop_404_no_bbox(auth_client, done_job_with_null_bbox):
    r = await auth_client.get(f"/api/jobs/{done_job_with_null_bbox}/regions/p1r0/crop")
    assert r.status_code == 404

async def test_crop_404_unknown_region(auth_client, done_job_with_bbox):
    r = await auth_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p9r9/crop")
    assert r.status_code == 404

async def test_crop_owner_only(auth_client, other_client, done_job_with_bbox):
    assert (await other_client.get(f"/api/jobs/{done_job_with_bbox}/regions/p1r0/crop")).status_code == 403
