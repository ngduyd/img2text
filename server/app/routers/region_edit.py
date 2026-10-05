"""Plan H Task 2: PATCH /api/jobs/{id}/regions/{rid} — per-region edit."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.routers.exports import current_markdown, find_region
from app.routers.jobs import _job_or_403
from app.storage import StorageDriver, get_storage

MAX_REGION_TEXT_CHARS = 10_000

router = APIRouter(tags=["regions"])

class RegionTextBody(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _nonempty_10k(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text không được để trống.")
        if len(v) > MAX_REGION_TEXT_CHARS:
            raise ValueError("text vượt quá 10000 ký tự.")
        return v

@router.patch("/api/jobs/{id}/regions/{rid}")
async def edit_region_text(
    id: int,
    rid: str,
    body: RegionTextBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    # deepcopy: nested region dicts are mutated below; a shallow copy would
    # share them with job.result and the JSON comparator sees no change
    result = copy.deepcopy(job.result or {})
    region = find_region(result, rid)
    if region is None:
        raise HTTPException(status_code=404, detail="region not found")
    old = region.get("text") or ""
    new = body.text
    region["text"] = new
    markdown_replaced = False
    if old and old != new:
        target = current_markdown(result)
        if old in target:
            result["edited_markdown"] = target.replace(old, new, 1)
            markdown_replaced = True
    job.result = result
    await session.commit()
    # cache invalidation: exported md must reflect the edit (Plan D binding,
    # same as patch_content); crops untouched — bboxes unchanged
    await storage.delete_prefix(f"exports/{id}/")
    return {"id": rid, "text": new, "markdown_replaced": markdown_replaced}
