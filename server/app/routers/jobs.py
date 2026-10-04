"""Task 2: POST /api/jobs — upload validation, sha256 dedupe, job create.
Task 3: GET /api/jobs, GET /api/jobs/{id}, GET /api/jobs/{id}/file.
"""

import hashlib
import hmac
import io
import secrets
import tempfile
from datetime import datetime, timedelta, timezone

from PIL import Image
from pypdf import PdfReader, PdfWriter
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, get_runner_key, require_ocr
from app.limiter import DailyCounter
from app.models import Job, User
from app.schemas import ResultBody
from app.storage import StorageDriver, get_storage

UPLOAD_DAILY_LIMIT = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 50
CHUNK_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
PRESIGN_EXPIRES_SECONDS = 3600
LEASE_MINUTES = 45
ERROR_MAX_CHARS = 500

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

@router.get("/api/jobs/next")  # BEFORE /api/jobs/{id}: "next" must not match {id}
async def next_job(
    _: str = Depends(get_runner_key),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
):
    """Claim oldest queued job; race-safe via FOR UPDATE SKIP LOCKED.

    Returns the claim payload, or a bare 204 Response when the queue is
    empty (Response return bypasses FastAPI response-model handling)."""
    job = (
        await session.execute(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return Response(status_code=204)
    now = _utcnow()
    token = secrets.token_urlsafe(32)
    job.status = "running"
    job.started_at = now
    job.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    job.worker_token = token
    # presign BEFORE commit: storage_key is known pre-commit; a presign
    # failure must leave the job queued, not running with an undiscoverable
    # worker_token (fix round 1).
    file_url = await storage.presign_get(job.storage_key, PRESIGN_EXPIRES_SECONDS)
    await session.commit()
    return {
        "job_id": job.id,
        "worker_token": token,
        "file_url": file_url,
        "file_type": job.file_type,
        "page_count": job.page_count,
    }

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

# ---- Task 4: worker protocol (next / heartbeat / result / fail) ----

class FailBody(BaseModel):
    error: str

def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" else None

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

async def _worker_job_or_401(
    session: AsyncSession, job_id: int, token: str | None
) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if (
        token is None
        or not token.isascii()  # compare_digest TypeError → 500 on non-ascii
        or job.worker_token is None
        or not hmac.compare_digest(token, job.worker_token)
    ):  # capability-token check (ruling R11)
        raise HTTPException(status_code=401, detail="bad worker token")
    return job

@router.post("/api/jobs/{id}/heartbeat")
async def heartbeat_job(
    id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    token = _bearer_token(request)
    now = _utcnow()
    job = await session.get(Job, id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if (
        token is None
        or not token.isascii()  # compare_digest TypeError → 500 on non-ascii
        or job.worker_token is None
        or not hmac.compare_digest(token, job.worker_token)
    ):  # capability-token check stays first (ruling R11)
        raise HTTPException(status_code=401, detail="bad worker token")
    # Ruling R17 (atomic heartbeat): token-first gate, then ONE conditional
    # UPDATE re-checks the claim at commit time — closes the read-guard-
    # commit TOCTOU (stale heartbeat after reaper requeue + reclaim would
    # extend the NEW claim's lease against a stale read). Uniform 409 detail
    # with /result and /fail; new lease value computed in Python from the
    # same `now` used in the WHERE.
    new_lease = now + timedelta(minutes=LEASE_MINUTES)
    rowcount = (
        await session.execute(
            update(Job)
            .where(
                Job.id == id,
                Job.status == "running",
                Job.lease_expires_at > now,
                Job.worker_token == token,
            )
            .values(lease_expires_at=new_lease)
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="job not runnable")
    await session.commit()
    return {"lease_expires_at": new_lease}

@router.post("/api/jobs/{id}/result")
async def submit_result(
    id: int,
    body: ResultBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    token = _bearer_token(request)
    now = _utcnow()
    job = await session.get(Job, id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    # precedence: not runnable → 409 before token check (brief: failed job
    # posts result with cleared token → 409, not 401).
    # Ruling R14 (accepted for MVP): 409-before-401 here leaks job
    # existence/status-class to callers who know the id. Internal runner
    # surface, no content disclosure; read paths ownership-enforced.
    # Hardening path: per-runner keys + internet exposure → move token
    # check first (consistent with heartbeat).
    if (
        job.status != "running"
        or job.lease_expires_at is None
        or job.lease_expires_at <= now
    ):
        raise HTTPException(status_code=409, detail="job not runnable")
    if (
        token is None
        or not token.isascii()  # compare_digest TypeError → 500 on non-ascii
        or job.worker_token is None
        or not hmac.compare_digest(token, job.worker_token)
    ):
        raise HTTPException(status_code=401, detail="bad worker token")
    # Atomic transition (fix round 1): ONE conditional UPDATE re-checks the
    # claim at commit time — closes the read-guard-commit TOCTOU (Task 5
    # reaper requeue between guard and commit; concurrent double-submit).
    # Token in WHERE too: a reaper requeue + reclaim by another worker
    # flips rowcount to 0 → 409 instead of marking their claim done and
    # clearing their fresh token.
    rowcount = (
        await session.execute(
            update(Job)
            .where(
                Job.id == id,
                Job.status == "running",
                Job.lease_expires_at > now,
                Job.worker_token == token,
            )
            .values(
                result=body.model_dump(),
                status="done",
                finished_at=now,
                worker_token=None,
                lease_expires_at=None,
            )
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="job not runnable")
    await session.commit()
    return {}

@router.post("/api/jobs/{id}/fail")
async def fail_job(
    id: int,
    body: FailBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    token = _bearer_token(request)
    await _worker_job_or_401(session, id, token)  # 401/404 gate before write
    # Atomic transition (ruling R16, same pattern as /result): ONE
    # conditional UPDATE re-checks the claim at commit time; a stale fail
    # after reaper requeue + reclaim flips rowcount to 0 → 409 instead of
    # marking another worker's claim failed / clearing their fresh token.
    # Lease check kept symmetric with /result.
    now = _utcnow()
    rowcount = (
        await session.execute(
            update(Job)
            .where(
                Job.id == id,
                Job.status == "running",
                Job.lease_expires_at > now,
                Job.worker_token == token,
            )
            .values(
                status="failed",
                error=body.error[:ERROR_MAX_CHARS],
                finished_at=now,
                worker_token=None,
                lease_expires_at=None,
            )
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="job not runnable")
    await session.commit()
    return {}
