"""Jobs router: upload, owner reads, worker claim/protocol, owner retry.

Sections: upload (Tasks 2) → owner reads (Task 3) → worker claim
(GET /api/jobs/next; route MUST stay before /{id}) → owner retry (Plan E,
Plan D binding: stale exports+crops deleted) → worker protocol (Task 4;
R11 capability token, R16/R17 atomic conditional-UPDATE transitions).
"""

import hashlib
import hmac
import json
import logging
import secrets
import tempfile
from datetime import datetime, timedelta, timezone

from pypdf import PdfReader
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_user, get_runner_key, require_ocr
from app.core.limiter import DailyCounter
from app.core.models import Job, User
from app.core.schemas import PreprocessIn, ResultBody
from app.services.job_results import store_worker_result
from app.services.storage import StorageDriver, get_storage

UPLOAD_DAILY_LIMIT = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 50
CHUNK_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
PRESIGN_EXPIRES_SECONDS = 3600
LEASE_MINUTES = 45
ERROR_MAX_CHARS = 500
ROTATE_ANGLES = {0, 90, 180, 270}

router = APIRouter(tags=["jobs"])
logger = logging.getLogger(__name__)

# Plan M: word style override enum + typed value rules (spec: keys subset,
# values typed; violation → 422 "Kiểu định dạng không hợp lệ.")
LAYOUT_STYLE_KEYS = {
    "fontFamily", "fontSize", "align", "indent", "spacing", "underline"
}
LAYOUT_ALIGNS = {"left", "center", "justify"}
LAYOUT_INDENTS = {0, 1, 2}
LAYOUT_SPACINGS = {1, 1.25, 1.5, 2}
LAYOUT_FONT_MAX_CHARS = 40
LAYOUT_FONT_SIZE_RANGE = range(8, 73)  # 8-72 inclusive


class LayoutStyleBody(BaseModel):
    # style: object|null (spec) — validate types manually to keep the
    # exact 422 detail "Kiểu định dạng không hợp lệ."
    style: dict | None


def _validate_layout_style(style: dict) -> None:
    """Enum keys + typed values; any violation → 422 (exact detail)."""
    def bad() -> HTTPException:
        return HTTPException(
            status_code=422, detail="Kiểu định dạng không hợp lệ."
        )

    if not set(style) <= LAYOUT_STYLE_KEYS:
        raise bad()
    for key, value in style.items():
        if key == "fontFamily":
            if not isinstance(value, str) or len(value) > LAYOUT_FONT_MAX_CHARS:
                raise bad()
        elif key == "fontSize":
            # bool is int subclass — reject explicitly (true ≠ 8-72)
            if type(value) is not int or value not in LAYOUT_FONT_SIZE_RANGE:
                raise bad()
        elif key == "align":
            if value not in LAYOUT_ALIGNS:
                raise bad()
        elif key == "indent":
            if type(value) is not int or value not in LAYOUT_INDENTS:
                raise bad()
        elif key == "spacing":
            if type(value) not in (int, float) or value not in LAYOUT_SPACINGS:
                raise bad()
        elif key == "underline":
            if not isinstance(value, bool):
                raise bad()

def _ocr_user(user: User = Depends(get_current_user)) -> User:
    return require_ocr(user)

def _pdf_page_count(tmp) -> int:
    return len(PdfReader(tmp).pages)

# --- Upload: POST /api/jobs (validation, sha256 dedupe, create) ---

@router.post("/api/jobs", status_code=201)
async def upload_job(
    request: Request,
    file: UploadFile = File(...),
    preprocess: str | None = Form(None),
    output_format: str | None = Form(None),
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
    # Plan D4: export format chosen at upload; invalid → 422 BEFORE any write
    fmt = output_format or "md"
    if fmt not in ("md", "docx"):
        raise HTTPException(status_code=422, detail="Đầu ra không hợp lệ.")

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
            try:
                page_count = _pdf_page_count(tmp)
            except Exception:
                # spec §6: corrupt/encrypted PDF is a synchronous 422,
                # never a 500, and no job row / storage write happens.
                raise HTTPException(
                    status_code=422, detail="File PDF không hợp lệ."
                )
            if page_count > MAX_PDF_PAGES:
                raise HTTPException(
                    status_code=422, detail="File PDF quá 50 trang."
                )
            file_type = "pdf"
        else:
            page_count = 1
            file_type = "image"
        # Plan W: preprocess validated AFTER page_count known, BEFORE storage.put
        preprocess_json: str | None = None
        if preprocess is not None:
            try:
                pp = PreprocessIn.model_validate(json.loads(preprocess))
            except (json.JSONDecodeError, ValidationError):
                raise HTTPException(422, detail="Preprocess không hợp lệ.")
            if pp.pages == []:
                raise HTTPException(422, detail="Chưa chọn trang nào.")
            if pp.pages is not None and any(
                p < 1 or p > page_count for p in pp.pages
            ):
                raise HTTPException(
                    422, detail="Trang chọn vượt quá số trang của file."
                )
            if file_type != "pdf":
                raise HTTPException(422, detail="Chỉ file PDF hỗ trợ chọn trang.")
            # ponytail: pages=None means "all pages" — rotate keys then skip
            # the selected-set check; add per-page bounds if wizard needs it.
            if pp.pages is not None:
                selected = set(pp.pages)
                for key in pp.rotate:
                    try:
                        if int(key) not in selected:
                            raise ValueError
                    except ValueError:
                        raise HTTPException(
                            422, detail="Xoay áp dụng cho trang đã chọn."
                        )
            for angle in pp.rotate.values():
                if angle not in ROTATE_ANGLES:
                    raise HTTPException(422, detail="Góc xoay không hợp lệ.")
            preprocess_json = json.dumps(pp.model_dump())
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
        preprocess=preprocess_json,
        output_format=fmt,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return {
        "id": job.id,
        "status": job.status,
        "page_count": job.page_count,
        "file_type": job.file_type,
        "output_format": fmt,
    }

# --- Owner reads: GET /api/jobs, /{id}, /{id}/file ---

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

# --- Worker claim: GET /api/jobs/next (route defined BEFORE /{id}) ---

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
        "preprocess": json.loads(job.preprocess) if job.preprocess else None,
    }

@router.get("/api/jobs/{id}")
async def get_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    # storage_key deliberately omitted — never leak bucket keys to users
    return {
        "id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "page_count": job.page_count,
        "error": job.error,
        "output_format": job.output_format or "md",
        "result": job.result if job.status == "done" else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        # Plan M: unified-editor contract — artifact cache flags + word style
        "layout_cache": {
            "md": await _layout_artifact_exists(storage, id, "md-layout"),
            "docx": await _layout_artifact_exists(storage, id, "docx-layout"),
        },
        "layout_style": _parse_layout_style(job),
    }

async def _layout_artifact_exists(
    storage: StorageDriver, job_id: int, fmt: str
) -> bool:
    """exports/{id}/{fmt} tồn tại? Storage lỗi → false + warning (không 500)."""
    try:
        return await storage.exists(f"exports/{job_id}/{fmt}")
    except Exception as exc:
        logger.warning(
            "layout_cache check failed job=%s fmt=%s: %s", job_id, fmt, exc
        )
        return False

def _parse_layout_style(job: Job) -> dict | None:
    """jobs.layout_style JSON → dict; broken JSON → None + warning."""
    if not job.layout_style:
        return None
    try:
        style = json.loads(job.layout_style)
    except (ValueError, TypeError) as exc:
        logger.warning("job %s layout_style JSON hỏng: %s", job.id, exc)
        return None
    return style if isinstance(style, dict) else None

@router.put("/api/jobs/{id}/layout-style", status_code=204)
async def put_layout_style(
    id: int,
    body: LayoutStyleBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Plan M: lưu word style override (object → cột JSON; null → xóa).

    Owner-or-admin (_job_or_403). Saved style must beat a previously
    cached docx-layout render → exports/{id}/docx-layout invalidated here
    (same cache-invalidation rule as PATCH /content, Plan M gates M3).
    """
    job = await _job_or_403(session, id, user)
    if body.style is None:
        job.layout_style = None
    else:
        _validate_layout_style(body.style)
        job.layout_style = json.dumps(body.style, ensure_ascii=False)
    await session.commit()
    # style đổi → render cached cũ hết hiệu lực (user style thắng LLM plan)
    await storage.delete_prefix(f"exports/{id}/docx-layout")
    return Response(status_code=204)

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

# --- Plan V (V2): same-origin original-file download (presign unreachable) ---

DOWNLOAD_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
}

@router.get("/api/jobs/{id}/file/download")
async def download_job_file(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Stream original bytes same-origin (Plan V V2; binding spec).

    Presigned localhost:4566 URLs unreachable via VSCode port-forward.
    storage_key already carries the "uploads/" prefix (upload_job builds
    the full key). Keys are hash.ext (ASCII-only) → job-{id}.{ext} filename;
    non-ascii never occurs, so no RFC 5987 filename* needed.
    """
    job = await _job_or_403(session, id, user)
    if not job.storage_key:  # pre-upload job row
        raise HTTPException(status_code=404, detail="Chưa có file.")
    try:
        data = await storage.get(job.storage_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy file.")
    ext = job.storage_key.rsplit(".", 1)[-1].lower() if "." in job.storage_key else ""
    media_type = DOWNLOAD_CONTENT_TYPES.get(ext, "application/octet-stream")
    filename = f"job-{id}.{ext}" if ext else f"job-{id}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# --- Owner retry: POST /api/jobs/{id}/retry (Plan D: no stale artifacts) ---

@router.post("/api/jobs/{id}/retry")
async def retry_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    """Requeue a failed job for its owner.

    OWNER semantics (contract): strict ownership — no admin bypass, unlike
    _job_or_403. Unknown → 404; other user → 403; not failed → 409.
    Deletes BOTH exports/{id}/ and crops/{id}/ prefixes BEFORE commit: a
    re-run may produce different regions/bboxes, so stale export bytes and
    old-bbox crops must not survive (Plan D final review, binding). Delete
    failure leaves the job failed (owner retries again) instead of queued
    with stale bytes.
    """
    job = await session.get(Job, id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    rowcount = (
        await session.execute(
            update(Job)
            .where(Job.id == id, Job.status == "failed")
            .values(
                status="queued",
                error=None,
                worker_token=None,
                lease_expires_at=None,
                started_at=None,
                finished_at=None,
            )
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="job not retryable")
    await storage.delete_prefix(f"exports/{id}/")
    await storage.delete_prefix(f"crops/{id}/")
    await session.commit()
    # ORM instance not expired (expire_on_commit=False): return known values
    return {"id": id, "status": "queued"}

# --- Worker protocol: heartbeat / result / fail (Task 4) ---

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
    storage: StorageDriver = Depends(get_storage),
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
    # Atomic transition (ruling R16/R17): ONE conditional UPDATE re-checks the
    # claim at commit time — service extracted in Plan K5 (shared with the
    # Kaggle batch orchestrator); behavior unchanged, guard identical.
    ok = await store_worker_result(
        session, id, body, token=token, now=now, storage=storage
    )
    if not ok:
        raise HTTPException(status_code=409, detail="job not runnable")
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
