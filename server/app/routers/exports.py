"""Plan D: PATCH /api/jobs/{id}/content + POST /api/jobs/{id}/export
+ GET /api/jobs/{id}/regions/{rid}/crop (lazy region crops, Task 2).

Task 1 ships the md branch; html/docx/pdf arrive in later tasks
(others → 501 for now).
"""

import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import Job, User
from app.routers.jobs import _job_or_403
from app.storage import StorageDriver, get_storage

EXPORT_PRESIGN_EXPIRES_SECONDS = 86400
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
CROP_MAX_WIDTH = 800
CROP_JPEG_QUALITY = 70

router = APIRouter(tags=["exports"])

def current_markdown(result: dict) -> str:
    """Latest markdown: user-edited wins over worker output (later tasks reuse)."""
    return result.get("edited_markdown") or result["markdown"]

def find_region(result: dict, rid: str) -> dict | None:
    """Region by id across all pages (later tasks reuse)."""
    for page in result.get("pages", []):
        for region in page.get("regions", []):
            if region["id"] == rid:
                return region
    return None

async def get_or_make_crop(
    job_id: int, rid: str, job: Job, result: dict, storage: StorageDriver
) -> str:
    """Lazy crop cache: crops/{job_id}/{rid}.jpg; returns storage key.

    Missing region/bbox None → KeyError (route maps to 404). Original
    missing in R2 → KeyError (route maps to 404 with spec §4 message).
    """
    key = f"crops/{job_id}/{rid}.jpg"
    region = find_region(result, rid)
    if region is None:
        raise KeyError(rid)
    bbox = region.get("bbox")
    if bbox is None:
        raise KeyError(rid)
    if await storage.exists(key):  # cache hit: presign only
        return key
    x1, y1, x2, y2 = bbox
    try:
        original = await storage.get(job.storage_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="File gốc không tồn tại.")
    img = Image.open(io.BytesIO(original))
    crop = img.crop((x1, y1, x2, y2))
    if crop.width > CROP_MAX_WIDTH:
        crop = crop.resize(
            (CROP_MAX_WIDTH, crop.height * CROP_MAX_WIDTH // crop.width)
        )
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=CROP_JPEG_QUALITY)
    await storage.put(key, buf.getvalue())
    return key

class ContentBody(BaseModel):
    markdown: str

    @field_validator("markdown")
    @classmethod
    def _nonempty_2mb(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("markdown không được để trống.")
        if len(v.encode()) > MAX_MARKDOWN_BYTES:
            raise ValueError("markdown vượt quá 2MB.")
        return v

class ExportBody(BaseModel):
    fmt: Literal["md", "html", "docx", "pdf"]

@router.patch("/api/jobs/{id}/content")
async def patch_content(
    id: int,
    body: ContentBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    result = dict(job.result or {})  # JSONB merge: copy, set, reassign
    result["edited_markdown"] = body.markdown
    job.result = result
    await session.commit()
    # cache invalidation: exported md must reflect the edit
    await storage.delete_prefix(f"exports/{id}/")
    return {}

@router.post("/api/jobs/{id}/export")
async def export_job(
    id: int,
    body: ExportBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    if body.fmt != "md":
        # ponytail: html/docx/pdf land in later Plan D tasks
        raise HTTPException(status_code=501, detail="Chưa hỗ trợ.")
    key = f"exports/{id}/md"
    if not await storage.exists(key):  # cache hit → presign only, no re-put
        await storage.put(key, current_markdown(job.result).encode())
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}

@router.get("/api/jobs/{id}/regions/{rid}/crop")
async def region_crop(
    id: int,
    rid: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    result = dict(job.result or {})
    try:
        key = await get_or_make_crop(id, rid, job, result, storage)
    except KeyError:
        raise HTTPException(status_code=404)
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}
