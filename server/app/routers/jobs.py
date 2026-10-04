"""Task 2: POST /api/jobs — upload validation, sha256 dedupe, job create.
Task 3: GET /api/jobs, GET /api/jobs/{id}, GET /api/jobs/{id}/file.
"""

import hashlib
import io
import tempfile

from PIL import Image
from pypdf import PdfReader, PdfWriter
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_ocr
from app.limiter import DailyCounter
from app.models import Job, User
from app.storage import StorageDriver, get_storage

UPLOAD_DAILY_LIMIT = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 50
CHUNK_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
PRESIGN_EXPIRES_SECONDS = 3600

router = APIRouter(tags=["jobs"])

def _ocr_user(user: User = Depends(get_current_user)) -> User:
    return require_ocr(user)

def _pdf_page_count(tmp) -> int:
    return len(PdfReader(tmp).pages)

@router.post("/api/jobs", status_code=201)
async def upload_job(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(_ocr_user),
    storage: StorageDriver = Depends(get_storage),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # lazy per-app instance; same pattern as auth SlidingWindow
    limiter = getattr(request.app.state, "upload_limiter", None)
    if limiter is None:
        limiter = request.app.state.upload_limiter = DailyCounter(UPLOAD_DAILY_LIMIT)
    if not limiter.check(f"upload:{user.id}"):
        raise HTTPException(
            status_code=429, detail="Đã đạt giới hạn upload hôm nay."
        )

    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Định dạng file không được hỗ trợ.")

    # hash while spooling to temp file; size cap enforced during the stream
    hasher = hashlib.sha256()
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as tmp:
        while chunk := await file.read(CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=422, detail="File vượt quá 50MB.")
            hasher.update(chunk)
            tmp.write(chunk)
        if ext == "pdf":
            page_count = _pdf_page_count(tmp)
            if page_count > MAX_PDF_PAGES:
                raise HTTPException(
                    status_code=422, detail="File PDF quá 50 trang."
                )
            file_type = "pdf"
        else:
            page_count = 1
            file_type = "image"
        key = f"uploads/{hasher.hexdigest()}.{ext}"
        # driver.put no-ops when the content-addressed key already exists
        tmp.seek(0)
        await storage.put(key, tmp.read())

    job = Job(
        user_id=user.id,
        status="queued",
        storage_key=key,
        file_type=file_type,
        page_count=page_count,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return {
        "id": job.id,
        "status": job.status,
        "page_count": job.page_count,
        "file_type": job.file_type,
    }

async def _job_or_403(
    session: AsyncSession, job_id: int, user: User
) -> Job:
    """Unknown id → 404; known but not owner (non-admin) → 403."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return job

@router.get("/api/jobs")
async def list_jobs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.execute(
            select(Job)
            .where(Job.user_id == user.id)
            .order_by(Job.created_at.desc())
        )
    ).scalars().all()
    items = [
        {
            "id": j.id,
            "status": j.status,
            "page_count": j.page_count,
            "file_type": j.file_type,
            "created_at": j.created_at,
            "error": j.error,
        }
        for j in rows
    ]
    return {"items": items, "total": len(items)}

@router.get("/api/jobs/{id}")
async def get_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    job = await _job_or_403(session, id, user)
    # storage_key deliberately omitted — never leak bucket keys to users
    return {
        "id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "page_count": job.page_count,
        "error": job.error,
        "result": job.result if job.status == "done" else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

@router.get("/api/jobs/{id}/file")
async def get_job_file(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    url = await storage.presign_get(job.storage_key, PRESIGN_EXPIRES_SECONDS)
    return {"url": url}
