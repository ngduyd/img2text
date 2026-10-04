"""Plan D: PATCH /api/jobs/{id}/content + POST /api/jobs/{id}/export
+ GET /api/jobs/{id}/regions/{rid}/crop (lazy region crops, Task 2)
+ html/docx export via pandoc + deploy/reference.docx (Task 3).

pdf stays 501 until Task 4.
"""

import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.convert import PANDOC_BIN, REFERENCE_DOCX
from app.db import get_session
from app.deps import get_current_user
from app.models import Job, User
from app.routers.jobs import _job_or_403
from app.storage import StorageDriver, get_storage

logger = logging.getLogger(__name__)

EXPORT_PRESIGN_EXPIRES_SECONDS = 86400
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
CROP_MAX_WIDTH = 800
CROP_JPEG_QUALITY = 70
PANDOC_TIMEOUT_SECONDS = 55
# Exact marker emitted by worker/pipeline.py for unextractable image regions.
_MARKER = "**[Hình ảnh chưa trích xuất: vùng {rid}]**"

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
    # no exif_transpose: crop must match VLM pixel frame (worker sees raw pixels)
    img = img.convert("RGB")  # RGBA/P-mode/WEBP originals cannot save as JPEG
    crop = img.crop((x1, y1, x2, y2))
    if crop.width > CROP_MAX_WIDTH:
        crop = crop.resize(
            (CROP_MAX_WIDTH, crop.height * CROP_MAX_WIDTH // crop.width)
        )
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=CROP_JPEG_QUALITY)
    await storage.put(key, buf.getvalue())
    return key

async def _materialize_crops(
    job_id: int, markdown: str, job: Job, storage: StorageDriver, tempdir: Path
) -> str:
    """Marker→image rewrite: materialize crops into tempdir/crops/{rid}.jpg.

    Region verdict image_unextractable WITH bbox → crop cached/generated,
    marker `**[Hình ảnh chưa trích xuất: vùng {rid}]**` replaced by
    `![vùng {rid}](crops/{rid}.jpg)`. bbox-less/missing regions keep the
    marker text (Plan D Global Constraints). Returns rewritten markdown.
    """
    result = dict(job.result or {})
    for page in result.get("pages", []):
        for region in page.get("regions", []):
            if region.get("verdict") != "image_unextractable":
                continue
            if region.get("bbox") is None:
                continue
            rid = region["id"]
            try:
                key = await get_or_make_crop(job_id, rid, job, result, storage)
                crop_bytes = await storage.get(key)
            except (KeyError, HTTPException):
                # missing region/bbox/original → marker survives (best-effort)
                continue
            crop_dir = tempdir / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            (crop_dir / f"{rid}.jpg").write_bytes(crop_bytes)
            markdown = markdown.replace(
                _MARKER.format(rid=rid), f"![vùng {rid}](crops/{rid}.jpg)"
            )
    return markdown

async def _pandoc_export(
    fmt: str, job_id: int, markdown: str, job: Job, storage: StorageDriver
) -> bytes:
    """pandoc markdown→fmt via tempdir (crops materialized first); 500 on failure."""
    with tempfile.TemporaryDirectory() as td:
        tempdir = Path(td)
        in_md = tempdir / "in.md"
        in_md.write_text(
            await _materialize_crops(job_id, markdown, job, storage, tempdir),
            encoding="utf-8",
        )
        out = tempdir / f"out.{fmt}"
        cmd = [PANDOC_BIN, "-f", "markdown", "-t", fmt]
        if fmt == "html":
            cmd.append("--standalone")
        else:  # docx: reference styles from committed deploy/reference.docx
            cmd += ["--reference-doc", REFERENCE_DOCX]
        cmd += ["-o", str(out), str(in_md)]
        try:
            # cwd=tempdir: markdown image paths (crops/{rid}.jpg) resolve here
            proc = subprocess.run(
                cmd, capture_output=True, timeout=PANDOC_TIMEOUT_SECONDS, cwd=str(tempdir)
            )
        except subprocess.TimeoutExpired:
            logger.warning("pandoc timed out fmt=%s job=%s", fmt, job_id)
            raise HTTPException(status_code=500, detail="Xuất file thất bại.")
        if proc.returncode != 0:
            # sanitized: stdout/stderr to log only, never the response body
            logger.warning(
                "pandoc failed fmt=%s job=%s rc=%s stderr=%s",
                fmt,
                job_id,
                proc.returncode,
                proc.stderr[:500],
            )
            raise HTTPException(status_code=500, detail="Xuất file thất bại.")
        return out.read_bytes()

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
    if body.fmt == "pdf":
        # ruling: pdf (weasyprint) lands in Task 4
        raise HTTPException(status_code=501, detail="Chưa hỗ trợ.")
    key = f"exports/{id}/{body.fmt}"
    if not await storage.exists(key):  # cache hit → presign only, no re-generate
        markdown = current_markdown(job.result or {})
        if body.fmt == "md":
            data = markdown.encode()
        else:  # html / docx via pandoc
            data = await _pandoc_export(body.fmt, id, markdown, job, storage)
        await storage.put(key, data)
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
    if job.file_type != "image":
        # ruling R26: PDF jobs have no PIL-decodable original
        raise HTTPException(status_code=404, detail="Crop chỉ hỗ trợ file ảnh.")
    result = dict(job.result or {})
    try:
        key = await get_or_make_crop(id, rid, job, result, storage)
    except KeyError:
        raise HTTPException(status_code=404)
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}
