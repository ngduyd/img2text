"""Plan D: PATCH /api/jobs/{id}/content + POST /api/jobs/{id}/export.

Task 1 ships the md branch; html/docx/pdf arrive in later tasks
(others → 501 for now).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import Job, User
from app.routers.jobs import _job_or_403
from app.storage import StorageDriver, get_storage

EXPORT_PRESIGN_EXPIRES_SECONDS = 86400
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024

router = APIRouter(tags=["exports"])

def current_markdown(result: dict) -> str:
    """Latest markdown: user-edited wins over worker output (later tasks reuse)."""
    return result.get("edited_markdown") or result["markdown"]

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
