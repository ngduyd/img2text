"""Jobs router: upload, owner reads, worker claim/protocol, owner retry.

Sections: presign + metadata create (R2, spec 2026-10-10) → owner reads (Task 3) → worker claim
(GET /api/jobs/next; route MUST stay before /{id}) → owner retry (Plan E,
Plan D binding: stale exports+crops deleted) → worker protocol (Task 4;
R11 capability token, R16/R17 atomic conditional-UPDATE transitions).
"""

import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, get_runner_key, require_ocr
from app.core.limiter import DailyCounter
from app.core.models import DocumentVersion, Job, OcrSuggestion, User, WorkerHeartbeat
from app.core.schemas import PreprocessIn, ResultBody
from app.services import proofread
from app.services.doc_versions import (
    latest_version,
    read_version,
    save_version,
    seed_current,
    snapshot_current_layout,
)
from app.services.job_results import _schedule_auto_output, store_worker_result
from app.services.quota import ensure_quota, quota_me
from app.services.layout_sync import (
    DOCX_HTML_KEY,
    DOCX_LAYOUT_KEY,
    MD_LAYOUT_KEY,
    sync_job_layouts,
)
from app.services.storage import StorageDriver, get_storage

UPLOAD_DAILY_LIMIT = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Spec 2026-10-10 sanity bound (was 50 on the removed server-side parse):
# the client counts pages with pdf.js; presign/create check the METADATA.
# P2-5: cap = settings.max_pages (1 config; default = kernel hard cap 100).
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf", "heic", "heif", "avif"}
# ext → canonical Content-Type (R2): presign binds the declared type to the
# extension allowlist; the Plan V download route reuses the same map.
CONTENT_TYPE_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "heic": "image/heic",
    "heif": "image/heif",
    "avif": "image/avif",
}
# content-addressed keys ONLY (sha256 hex from presign; legacy multipart keys
# were built the same way) — trust boundary: a crafted key must not point the
# create head-check at arbitrary storage paths.
STORAGE_KEY_RE = re.compile(r"uploads/[0-9a-f]{64}\.(?:jpg|jpeg|png|webp|pdf|heic|heif|avif)")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
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
    """Enum keys + typed values; any violation → 422 (exact detail).

    BUGFIX 2: web sends fontSize/spacing as STRING from <select>/inputs —
    numeric strings are coerced in place (style dict normalized to int/float)
    before the route json.dumps it; unparseable/out-of-range → 422.
    """
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
            if isinstance(value, str):
                try:
                    value = int(value)
                except ValueError:
                    raise bad() from None
                style[key] = value
            if type(value) is not int or value not in LAYOUT_FONT_SIZE_RANGE:
                raise bad()
        elif key == "align":
            if value not in LAYOUT_ALIGNS:
                raise bad()
        elif key == "indent":
            if type(value) is not int or value not in LAYOUT_INDENTS:
                raise bad()
        elif key == "spacing":
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    raise bad() from None
                style[key] = value
            if type(value) not in (int, float) or value not in LAYOUT_SPACINGS:
                raise bad()
        elif key == "underline":
            if not isinstance(value, bool):
                raise bad()

def _ocr_user(user: User = Depends(get_current_user)) -> User:
    return require_ocr(user)

# --- Presign: POST /api/jobs/presign (spec 2026-10-10, R2 direct upload) ---

class PresignBody(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    # Client-computed content hash: storage_key = uploads/{sha256}.{ext}
    # (content-addressed → dedupe + the pipeline manifest carries it).
    sha256: str
    # Optional: the UI uploads FIRST (progress bar) and counts pages after
    # with pdf.js → checked here when given, authoritatively at POST /api/jobs.
    page_count: int | None = None
    output_format: str = "md"
    mode: str = "layout"

class JobCreateBody(BaseModel):
    """Metadata-only create — bytes already went browser → storage via the
    presigned PUT (the multipart UploadFile path is removed)."""

    storage_key: str
    page_count: int
    # wave-2 #3: tên file gốc (search q ILIKE); web cũ không gửi → None.
    filename: str | None = None
    output_format: str = "md"
    mode: str = "layout"
    # Plan W (wizard): page selection + rotation JSON object, not a string.
    preprocess: dict | None = None

def _clean_filename(name: str | None) -> str | None:
    """wave-2 #3 trust boundary: metadata only (KHÔNG BAO GIỜ làm path) —
    strip, không rỗng, ≤255, không path separator/NUL."""
    if name is None:
        return None
    name = name.strip()
    if not name or len(name) > 255 or any(c in name for c in "/\\\x00"):
        raise HTTPException(status_code=422, detail="Tên file không hợp lệ.")
    return name

def _file_ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""

def _validate_output_settings(output_format: str, mode: str) -> None:
    """Plan D4 + Phase 5 enums; invalid → exact-VN 422 BEFORE any write."""
    if output_format not in ("md", "docx"):
        raise HTTPException(status_code=422, detail="Đầu ra không hợp lệ.")
    if mode not in ("layout", "extract_only"):
        raise HTTPException(status_code=422, detail="Chế độ xử lý không hợp lệ.")

def _sniff_kind(data: bytes) -> str | None:
    """Magic-byte cross-check vs declared ext (spec 2026-10-13 §9b): metadata
    is primary, sniff catches real mismatches ('.jpg' containing %PDF →
    kernel 'cannot identify image file'). None = unidentified → pass
    (no false positives on legit files with odd prefixes)."""
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    # ISO-BMFF ftyp: quét TOÀN BỘ box — major brand alone miss avif file
    # major-brand mif1 (generic container); avif/avis check TRƯỚC mif1.
    box_size = int.from_bytes(data[:4], "big")
    ftyp = (
        data[4:box_size]
        if data[4:8] == b"ftyp" and box_size <= len(data)
        else data[4:12]
    )
    if b"avif" in ftyp or b"avis" in ftyp:
        return "avif"
    if b"heic" in ftyp or b"heix" in ftyp or b"mif1" in ftyp:
        return "heic"
    return None

def _bad_page_count(ext: str, page_count: int) -> str | None:
    """pdf → ≤ settings.max_pages (P2-5: 1 config); image = 1 (rasterization
    always yields one page). None = ok."""
    if page_count < 1:
        return "Số trang không hợp lệ."
    if ext == "pdf":
        if page_count > settings.max_pages:
            return f"File PDF quá {settings.max_pages} trang."
    elif page_count != 1:
        return "Số trang không hợp lệ."
    return None

@router.get("/api/quota/me")
async def my_quota(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """WS-ADMIN: quota hiện tại của user (widget Jobs header)."""
    return await quota_me(session, user)

@router.post("/api/jobs/presign")
async def presign_upload(
    body: PresignBody,
    user: User = Depends(_ocr_user),
    storage: StorageDriver = Depends(get_storage),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Presigned PUT URL: sanity-check metadata (declared size, page bound,
    enums) → content-addressed key → signed URL. The backend never touches
    the bytes; the 50MB cap is verified AFTER upload (create head-check)."""
    ext = _file_ext(body.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422, detail="Định dạng file không được hỗ trợ."
        )
    # browser không chuẩn (Android/Windows) report .jpg là image/jpg —
    # alias cùng media type (RFC 2046) map về image/jpeg trước validate.
    declared = {"image/jpg": "image/jpeg"}.get(body.content_type, body.content_type)
    if declared != CONTENT_TYPE_BY_EXT[ext]:
        raise HTTPException(
            status_code=422, detail="Định dạng file không được hỗ trợ."
        )
    if not 0 < body.size_bytes <= MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="File vượt quá 50MB.")
    _validate_output_settings(body.output_format, body.mode)
    if body.page_count is not None:
        bad = _bad_page_count(ext, body.page_count)
        if bad is not None:
            raise HTTPException(status_code=422, detail=bad)
    sha = body.sha256.lower()
    if not SHA256_RE.fullmatch(sha):
        raise HTTPException(status_code=422, detail="sha256 không hợp lệ.")
    # WS-ADMIN quota: pre-create gate (page_count None → coi như 1 trang)
    await ensure_quota(session, user, body.page_count)
    key = f"uploads/{sha}.{ext}"
    try:
        url = await storage.presign_put(key, PRESIGN_EXPIRES_SECONDS)
    except Exception as exc:
        logger.exception("presign_put failed key=%s", key)
        raise HTTPException(
            status_code=500, detail="Không tạo được link tải lên."
        ) from exc
    return {
        "storage_key": key,
        "url": url,
        "max_bytes": MAX_UPLOAD_BYTES,
    }

@router.post("/api/jobs", status_code=201)
async def create_job(
    request: Request,
    body: JobCreateBody,
    user: User = Depends(_ocr_user),
    storage: StorageDriver = Depends(get_storage),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Metadata-only job create: verify the presigned upload (head —
    no byte read; missing → 404 "File chưa tải lên.") then store metadata.
    PUT presign has no policy cap → 50MB enforced HERE post-upload:
    oversize → delete object + 422. Page count is client-side (pdf.js) —
    bounded here."""
    # lazy per-app instance; same pattern as auth SlidingWindow
    limiter = getattr(request.app.state, "upload_limiter", None)
    if limiter is None:
        limiter = request.app.state.upload_limiter = DailyCounter(UPLOAD_DAILY_LIMIT)
    if not limiter.check(f"upload:{user.id}"):
        raise HTTPException(
            status_code=429, detail="Đã đạt giới hạn upload hôm nay."
        )
    _validate_output_settings(body.output_format, body.mode)
    if not STORAGE_KEY_RE.fullmatch(body.storage_key):
        raise HTTPException(
            status_code=422, detail="Đường dẫn file không hợp lệ."
        )
    ext = body.storage_key.rsplit(".", 1)[-1].lower()
    try:
        size = await storage.size(body.storage_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="File chưa tải lên.")
    if size > MAX_UPLOAD_BYTES:
        # PUT presign không kí content-length-range → cap verify sau upload;
        # oversize object = junk, xóa ngay (content-addressed key dedupe).
        await storage.delete_prefix(body.storage_key)
        raise HTTPException(status_code=422, detail="File vượt quá 50MB.")
    # Magic-byte cross-check (spec §9b): metadata là primary, sniff chặn
    # file sai đuôi thật sự; unidentified bytes pass (no false positive).
    sniff_ext = {"jpeg": "jpg"}.get(ext, ext)
    kind = _sniff_kind(await storage.get(body.storage_key))
    # heic/heif là CÙNG 1 định dạng (brand "heic" cho cả 2 đuôi) — normalize
    # thành 1 nhóm trước khi so, không 422 oan file .heif thật.
    heif_bytes = kind == "heic" and sniff_ext in {"heic", "heif"}
    if kind is not None and kind != sniff_ext and not heif_bytes:
        await storage.delete_prefix(body.storage_key)
        raise HTTPException(
            status_code=422,
            detail=f"File (.{ext}) không khớp nội dung file ({kind} thật)",
        )
    bad = _bad_page_count(ext, body.page_count)
    if bad is not None:
        raise HTTPException(status_code=422, detail=bad)
    # WS-ADMIN quota: pre-create gate SAU các 422 validation (giữ 422 pin),
    # TRƯỚC khi insert row.
    await ensure_quota(session, user, body.page_count)
    filename = _clean_filename(body.filename)
    file_type = "pdf" if ext == "pdf" else "image"
    # Plan W: preprocess validated AFTER page_count known, BEFORE the row write
    preprocess_json: str | None = None
    if body.preprocess is not None:
        try:
            pp = PreprocessIn.model_validate(body.preprocess)
        except ValidationError:
            raise HTTPException(422, detail="Preprocess không hợp lệ.")
        if pp.pages == []:
            raise HTTPException(422, detail="Chưa chọn trang nào.")
        if pp.pages is not None and any(
            p < 1 or p > body.page_count for p in pp.pages
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
    job = Job(
        user_id=user.id,
        status="queued",
        storage_key=body.storage_key,
        filename=filename,
        file_type=file_type,
        page_count=body.page_count,
        preprocess=preprocess_json,
        output_format=body.output_format,
        mode=body.mode,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return {
        "id": job.id,
        "status": job.status,
        "page_count": job.page_count,
        "file_type": job.file_type,
        # review r1 P1-6: filename nhất quán list/detail/create (wave2-web)
        "filename": filename,
        "output_format": body.output_format,
        "mode": body.mode,
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
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    # wave-2 #3 (spec 2026-10-14): search + status tab + sort lên server.
    q: str | None = Query(None, max_length=255),
    status: str | None = Query(None, max_length=20),
    sort: Literal["newest", "oldest"] = "newest",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Paginated owner list (Phase 4): page/page_size in, {items,total,page,page_size}.

    total counts ALL owner jobs matching the FILTER (unpaginated) so the UI
    can render page numbers; id tiebreak keeps created_at ties from
    shuffling rows across page boundaries (pages must partition cleanly).
    q → ILIKE filename (filename NULL = legacy row, không khớp); status =
    single value; sort=newest|oldest (default newest, spec 2026-10-14 #3).
    """
    base = select(Job).where(Job.user_id == user.id)
    if (q or "").strip():
        # review r1 P1-2: escape %, _, \ → q là literal, không wildcard
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        base = base.where(Job.filename.ilike(f"%{needle}%", escape="\\"))
    if status:
        base = base.where(Job.status == status)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    order = (
        (Job.created_at.asc(), Job.id.asc())
        if sort == "oldest"
        else (Job.created_at.desc(), Job.id.desc())
    )
    rows = (
        await session.execute(
            base.order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    items = [
        {
            "id": j.id,
            "status": j.status,
            "page_count": j.page_count,
            "file_type": j.file_type,
            # wave2-web contract: hiển thị + toast (nullable = legacy row)
            "filename": j.filename,
            "created_at": j.created_at,
            "error": j.error,
        }
        for j in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}

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
    job.status = "extracting"
    job.started_at = now
    job.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    job.worker_token = token
    # presign BEFORE commit: storage_key is known pre-commit; a presign
    # failure must leave the job queued, not extracting with an
    # undiscoverable worker_token (fix round 1).
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
    docx_html = await _layout_artifact_exists(storage, id, "docx.html")
    # P0-D: web contract — text_version + kinds whose layout version row is
    # based on an older text (re-render needed); no version row → not stale
    stale_layouts: list[str] = []
    for kind, label in (("md-layout", "md"), ("docx-layout", "docx")):
        row = await latest_version(session, id, kind)
        if row is not None and row.based_on_text_version < job.text_version:
            stale_layouts.append(label)
    return {
        "id": job.id,
        "status": job.status,
        "file_type": job.file_type,
        "page_count": job.page_count,
        # review r1 P1-6: filename đã có ở list → detail/create đồng bộ
        "filename": job.filename,
        "error": job.error,
        "output_format": job.output_format or "md",
        # P1-2 review r1: web ẩn Section Layout + export nhóm layout khi extract_only
        "mode": job.mode or "layout",
        "result": job.result if job.status == "done" else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "text_version": job.text_version,
        "stale_layouts": stale_layouts,
        # Plan M: unified-editor contract — artifact cache flags + word style
        # Plan M3: docx = docx.html (user-edited) OR docx-layout (LLM render)
        "layout_cache": {
            "md": await _layout_artifact_exists(storage, id, "md-layout"),
            "docx": docx_html or await _layout_artifact_exists(
                storage, id, "docx-layout"
            ),
            "docx_html": docx_html,
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

@router.get("/api/jobs/{id}/ir")
async def get_job_ir(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get Document IR JSON for a job (if LLM produced one)."""
    job = await _job_or_403(session, id, user)
    if not job.ir_json:
        raise HTTPException(status_code=404, detail="Chưa có IR.")
    try:
        return json.loads(job.ir_json)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=500, detail="IR JSON hỏng.") from exc

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

DOWNLOAD_CONTENT_TYPES = CONTENT_TYPE_BY_EXT  # same ext→type map

@router.get("/api/jobs/{id}/file/download")
async def download_job_file(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Stream original bytes same-origin (Plan V V2; binding spec).

    Presigned localhost:4566 URLs unreachable via VSCode port-forward.
    storage_key already carries the "uploads/" prefix (create_job builds
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

# --- Per-step retry: POST /api/jobs/{id}/retry (spec 2026-10-09) ---

@router.post("/api/jobs/{id}/retry", status_code=204)
async def retry_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Unified per-step retry: failed ONLY (else 409), owner-strict.

    OWNER semantics (contract): strict ownership — no admin bypass, unlike
    _job_or_403. Unknown → 404; other user → 403; not failed → 409.
    Branch on failed_step (NULL = legacy failed row → extracting path):
    - "rendering": keep `failed` while the layout re-run is in flight; the
      auto-output completion flips it to done / failed+rendering (same
      rule as ingest). OCR result untouched — no cache deletion.
    - "extracting" (or NULL): back to queued (respawn on the next
      orchestrator tick) and BOTH exports/{id}/ and crops/{id}/ prefixes
      are deleted BEFORE commit: a re-run may produce different
      regions/bboxes, so stale export bytes and old-bbox crops must not
      survive (Plan D final review, binding). Delete failure leaves the
      job failed (owner retries again) instead of queued with stale bytes.
    """
    job = await session.get(Job, id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="job not retryable")
    if job.failed_step == "rendering":
        _schedule_auto_output(job, storage)  # fire-and-forget; 204 now
        return Response(status_code=204)
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
                failed_step=None,
            )
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="job not retryable")
    await storage.delete_prefix(f"exports/{id}/")
    await storage.delete_prefix(f"crops/{id}/")
    await session.commit()
    return Response(status_code=204)

# --- Retry layout gen: POST /api/jobs/{id}/retry-layout (LLM re-run) ---

@router.post("/api/jobs/{id}/retry-layout")
async def retry_layout(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    """Re-run layout gen (md-layout + docx-layout) for a done job.

    Layout gen is post-OCR fire-and-forget: works regardless of job
    status, no 409 gate. Each format is independent inside
    auto_generate_output (one failing logs a warning, the other still
    generates). Returns which layouts exist after the attempt.
    """
    job = await _job_or_403(session, id, user)
    # lazy import: exports → jobs (cycle if eager)
    from app.routers.exports import auto_generate_output
    await auto_generate_output(job, storage)
    return {
        "md": await storage.exists(f"exports/{id}/md-layout"),
        "docx": await storage.exists(f"exports/{id}/docx-layout"),
    }

# --- Plan proofread: gợi ý sửa lỗi OCR (LLM best-effort, user quyết định) ---

def _suggestion_out(s: OcrSuggestion) -> dict:
    return {
        "id": s.id,
        "page_index": s.page_index,
        "start": s.start,
        "end": s.end,
        "original": s.original,
        "suggestion": s.suggestion,
        "reason": s.reason,
        "status": s.status,
    }

async def _set_suggestion_status(
    session: AsyncSession, job_id: int, sid: int, status: str
) -> dict:
    """Status-only transition — client tự replace trong editor rồi PUT save."""
    rowcount = (
        await session.execute(
            update(OcrSuggestion)
            .where(OcrSuggestion.id == sid, OcrSuggestion.job_id == job_id)
            .values(status=status)
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="suggestion not found")
    await session.commit()
    return {"status": status}

@router.get("/api/jobs/{id}/suggestions")
async def list_suggestions(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Owner-or-admin: pending trước (mới nhất trước), rồi status khác."""
    await _job_or_403(session, id, user)
    rows = (
        await session.execute(
            select(OcrSuggestion)
            .where(OcrSuggestion.job_id == id)
            .order_by(
                (OcrSuggestion.status == "pending").desc(),
                OcrSuggestion.created_at.desc(),
                OcrSuggestion.id.desc(),
            )
        )
    ).scalars().all()
    return [_suggestion_out(s) for s in rows]

@router.post("/api/jobs/{id}/suggestions/{sid}/accept")
async def accept_suggestion(
    id: int,
    sid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _job_or_403(session, id, user)
    return await _set_suggestion_status(session, id, sid, "accepted")

@router.post("/api/jobs/{id}/suggestions/{sid}/reject")
async def reject_suggestion(
    id: int,
    sid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _job_or_403(session, id, user)
    return await _set_suggestion_status(session, id, sid, "rejected")

@router.post("/api/jobs/{id}/proofread")
async def proofread_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Nút refresh: chạy lại proofread thủ công → số gợi ý; LLM down → 0."""
    job = await _job_or_403(session, id, user)
    count = await proofread.run_proofread(session, job)
    return {"count": count}

# --- Phase 1 (spec Sub-system A): extraction save + incremental sync ---

MAX_EXTRACTION_CHARS = 2_000_000

class ExtractionBody(BaseModel):
    text: str
    old_phrase: str | None = None
    new_phrase: str | None = None
    expected_text_version: int
    # spec conflict flow: detached layout → 409 → UI confirms → force=True
    # overwrites (version history holds the pre-overwrite snapshot).
    force: bool = False

def _extraction_text(result: dict) -> str:
    """Derived text gốc: regions join \n, pages join \n\n (pre-edit jobs)."""
    pages = result.get("pages") or []
    return "\n\n".join(
        "\n".join(r.get("text") or "" for r in p.get("regions", []))
        for p in pages
    )

def _text_bytes(result: dict) -> bytes:
    """extraction_text nếu có, không thì derive từ regions — seed/trước-sửa
    và snapshot/sau-sửa đều đi qua đây (một spelling cho khái niệm text gốc)."""
    return (result.get("extraction_text") or _extraction_text(result)).encode(
        "utf-8"
    )

def _result_bytes(result: dict) -> bytes:
    """job.result JSON — snapshot kind "md": region edit sửa chính result
    (extraction_text không đổi → kind-text không phản ánh edit)."""
    return json.dumps(result, ensure_ascii=False).encode("utf-8")

async def _detached_kinds(
    session: AsyncSession, job_id: int, storage: StorageDriver
) -> set[str]:
    """Layout kinds whose latest version is a direct-edit (detached) snapshot."""
    out: set[str] = set()
    for kind in ("md-layout", "docx-layout"):
        row = await latest_version(session, job_id, kind)
        if row is not None and row.detached:
            out.add(kind)
    return out

async def _seed_versions(
    session: AsyncSession, job: Job, storage: StorageDriver
) -> None:
    """Lazy-seed version 1 for text + existing layouts on first access."""
    if await latest_version(session, job.id, "text") is None:
        await seed_current(
            storage, job.id, "text", _text_bytes(job.result or {}),
            job.text_version, session=session,
        )
    for kind, key in (
        ("md-layout", MD_LAYOUT_KEY.format(job_id=job.id)),
        ("docx-layout", DOCX_HTML_KEY.format(job_id=job.id)),
    ):
        if await latest_version(session, job.id, kind) is not None:
            continue
        if await storage.exists(key):
            await seed_current(
                storage, job.id, kind, await storage.get(key),
                job.text_version, session=session,
            )

async def bump_text_after_edit(
    session: AsyncSession,
    storage: StorageDriver,
    job: Job,
    data: bytes | None = None,
    seed_bytes: bytes | None = None,
    kind: str = "text",
) -> int:
    """content/region edit → bump jobs.text_version + snapshot 1 kind.

    kind "text" = text gốc (content edit); kind "md" = job.result JSON
    (region edit — content region edit sửa thật sự; extraction_text giữ
    nguyên → dual-truth deferred).
    seed_bytes = bản gốc TRƯỚC mutate (caller capture trước khi ghi job.result)
    → version 1 không bị bản đã sửa nuốt mất. data = bytes snapshot sau edit
    (mặc định derive từ job.result đã sửa; content edit truyền edited_markdown).
    Snapshot based_on = version mới → GET job stale_layouts + version history
    tự thấy edit.
    P1-2 round 2: seed + save KHÔNG tự commit → MỘT commit cuối gom
    result + 2 version row + bump; save_version nổ = chưa commit gì.
    """
    text = data if data is not None else _text_bytes(job.result or {})
    new_version = job.text_version + 1
    await seed_current(
        storage, job.id, kind, seed_bytes if seed_bytes is not None else text,
        job.text_version, session=session, commit=False,
    )
    await save_version(
        storage, job.id, kind, text, new_version, session=session, commit=False
    )
    job.text_version = new_version
    await session.commit()
    return job.text_version

@router.get("/api/jobs/{id}/extraction")
async def get_extraction(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    """text gốc (result extraction_text, else derived from regions) + version."""
    job = await _job_or_403(session, id, user)
    # WS-UI: section "Văn bản" đọc text ngay khi status == "rendering" (OCR xong).
    if job.status not in ("done", "rendering"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    await _seed_versions(session, job, storage)
    result = job.result or {}
    return {
        "text": result.get("extraction_text") or _extraction_text(result),
        "text_version": job.text_version,
    }

@router.post("/api/jobs/{id}/extraction")
async def post_extraction(
    id: int,
    body: ExtractionBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    """Save text gốc + bump text_version + incremental layout sync (0 LLM).

    Optimistic lock: expected_text_version mismatch → 409. Detached layout
    (direct edit) → 409 conflict unless force (UI-confirm overwrite).
    Per-layout atomic: phrase not found / artifact missing → layout NOT
    touched → needs_render entry, other layouts still synced.

    WS-SERVER queue: save khi status == "rendering" được phép (200) → set
    ``rerender_requested``; finalize render sẽ vẽ lại tối đa 1 lần (guard 2).
    mode == "extract_only" không bao giờ set cờ. Response thêm
    ``requires_rerender``.
    """
    job = await _job_or_403(session, id, user)
    if job.status not in ("done", "rendering"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    was_rendering = job.status == "rendering"
    extract_only = (job.mode or "layout") == "extract_only"
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Nội dung trống.")
    if len(body.text) > MAX_EXTRACTION_CHARS:
        raise HTTPException(status_code=422, detail="Nội dung quá dài.")
    if body.expected_text_version != job.text_version:
        raise HTTPException(
            status_code=409, detail="Nội dung đã thay đổi ở nơi khác. Tải lại trang."
        )
    detached = await _detached_kinds(session, id, storage)
    if detached and not body.force:
        raise HTTPException(
            status_code=409, detail="Layout có chỉnh tay. Đồng bộ sẽ ghi đè."
        )
    # 1) persist text + bump + snapshot — P1-4: ONE conditional UPDATE
    #    re-checks expected_text_version at commit time (atomic; closes the
    #    check-then-set race: loser gets rowcount=0 → 409, never a silent
    #    last-win overwrite nor a UNIQUE version clash).
    result = dict(job.result or {})
    result["extraction_text"] = body.text
    new_version = body.expected_text_version + 1
    # Save khi rendering → cờ vẽ lại nằm NGAY trong conditional UPDATE
    # (atomic với save — finalize không thể lọt giữa check và set).
    values: dict = {"result": result, "text_version": new_version}
    if was_rendering and not extract_only:
        values["rerender_requested"] = True
    rowcount = (
        await session.execute(
            update(Job)
            .where(
                Job.id == id,
                Job.status.in_(("done", "rendering")),
                Job.text_version == body.expected_text_version,
            )
            .values(**values)
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(
            status_code=409, detail="Nội dung đã thay đổi ở nơi khác. Tải lại trang."
        )
    job.text_version = new_version
    await session.commit()
    await save_version(
        storage, id, "text", body.text.encode("utf-8"), job.text_version,
        session=session,
    )
    # 2) per-layout incremental sync (skip detached unless force); snapshot
    #    synced artifact (based_on = new text_version, detached cleared)
    synced: dict[str, bool] = {"md": False, "docx": False}
    exists = {
        "md": await storage.exists(MD_LAYOUT_KEY.format(job_id=id)),
        "docx": await storage.exists(DOCX_HTML_KEY.format(job_id=id)),
    }
    needs_render: list[str] = []
    # P1-1: empty/None old OR new → skip sync entirely (old="" would
    # "replace" between every character and corrupt the artifact).
    # P2-4: save khi rendering → BỎ sync (read-modify-write trên artifact
    # đang bị render task ghi) — chỉ bump version + flag; pass render sau
    # vẽ lại từ text mới.
    if body.old_phrase and body.new_phrase and not was_rendering:
        # detached kinds 409'd above unless force → force overwrites them
        synced = await sync_job_layouts(
            storage, id, body.old_phrase, body.new_phrase
        )
        for kind, flag in (("md-layout", "md"), ("docx-layout", "docx")):
            if not synced[flag]:
                continue
            key = (
                MD_LAYOUT_KEY.format(job_id=id)
                if flag == "md"
                else DOCX_HTML_KEY.format(job_id=id)
            )
            await save_version(
                storage, id, kind, await storage.get(key), job.text_version,
                session=session,
            )
        needs_render = [
            kind
            for kind, flag in (("md-layout", "md"), ("docx-layout", "docx"))
            if exists[flag] and not synced[flag] and kind not in detached
        ]
    # Done job: layout artifact tồn tại && sync targeted-fail → cờ vẽ lại.
    # (rendering case đã set trong UPDATE phía trên; extract_only không set.)
    requires_rerender = (not extract_only) and (
        was_rendering or bool(needs_render)
    )
    if requires_rerender and not was_rendering:
        await session.execute(
            update(Job).where(Job.id == id).values(rerender_requested=True)
        )
        await session.commit()
    return {
        "synced": synced,
        "needs_render": needs_render,
        "text_version": job.text_version,
        "requires_rerender": requires_rerender,
    }

@router.get("/api/jobs/{id}/versions")
async def list_versions(
    id: int,
    kind: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Version metadata (never storage keys); newest first."""
    await _job_or_403(session, id, user)
    stmt = select(DocumentVersion).where(DocumentVersion.job_id == id)
    if kind is not None:
        stmt = stmt.where(DocumentVersion.kind == kind)
    rows = (
        await session.execute(stmt.order_by(DocumentVersion.version.desc()))
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "version": r.version,
                "based_on_text_version": r.based_on_text_version,
                "detached": r.detached,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }

@router.post("/api/jobs/{id}/versions/{vid}/restore", status_code=204)
async def restore_version(
    id: int,
    vid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Restore = snapshot written as a NEW version (history append-only)."""
    await _job_or_403(session, id, user)
    row = await session.get(DocumentVersion, vid)
    if row is None or row.job_id != id:
        raise HTTPException(status_code=404, detail="version not found")
    data = await read_version(storage, row)
    job = await session.get(Job, id)
    if row.kind == "text":
        result = dict(job.result or {})
        result["extraction_text"] = data.decode("utf-8")
        job.result = result
        job.text_version += 1
        await session.commit()
        await save_version(
            storage, id, "text", data, job.text_version, session=session
        )
        return Response(status_code=204)
    if row.kind == "md":
        # P1-1 round 2: kind "md" = JSON job.result → restore trả result về
        # bản chụp, append-only như kind text; export dẫn xuất chết theo
        job.result = json.loads(data)
        job.text_version += 1
        await session.commit()
        await save_version(
            storage, id, "md", data, job.text_version, session=session
        )
        await storage.delete_prefix(f"exports/{id}/")
        return Response(status_code=204)
    if row.kind == "md-layout":
        key = MD_LAYOUT_KEY.format(job_id=id)
    elif data.startswith(b"PK\x03\x04"):
        # kind docx-layout chứa CẢ binary render (P2-4 fallback snapshot)
        # lẫn docx.html HTML (seed/edit/sync) → phân loại theo bytes: binary
        # phải về DOCX_LAYOUT_KEY, ghi vào docx.html sẽ 500 (.decode utf-8).
        key = DOCX_LAYOUT_KEY.format(job_id=id)
    else:
        key = DOCX_HTML_KEY.format(job_id=id)
    # P2: snapshot the current artifact BEFORE the overwrite — crash-safe
    # provenance (pre-restore bytes stay in version history).
    await snapshot_current_layout(
        storage, session, id, row.kind, job.text_version
    )
    if row.kind == "docx-layout" and key == DOCX_HTML_KEY.format(job_id=id):
        # supersede rule: derived exports/{id}/docx* die with the html edit
        await storage.delete_prefix(f"exports/{id}/docx")
    else:
        await storage.delete_prefix(key)
    await storage.put(key, data)
    await save_version(
        storage, id, row.kind, data, row.based_on_text_version,
        detached=False, session=session,
    )
    return Response(status_code=204)

# --- wave-2 #7: POST /api/worker/heartbeat (liveness upsert, runner key) -----

class WorkerHeartbeatBody(BaseModel):
    worker_id: str
    # "loop" mặc định (Colab loop); orchestrator ghi trực tiếp kind="kaggle-batch"
    kind: str = "loop"
    current_job_id: int | None = None

@router.post("/api/worker/heartbeat")
async def worker_heartbeat(
    body: WorkerHeartbeatBody,
    _: str = Depends(get_runner_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """spec 2026-10-14 #7: upsert last_seen/current_job_id (1 row/worker_id).
    Auth = runner key (cùng worker surface với GET /api/jobs/next — loop
    chưa có per-job token khi bắt đầu heartbeat)."""
    worker_id = body.worker_id.strip()
    kind = body.kind.strip() or "loop"
    if not worker_id or len(worker_id) > 100:
        # review r1 P2: tách message theo field hỏng (kind riêng, không gộp)
        raise HTTPException(status_code=422, detail="worker_id không hợp lệ.")
    if len(kind) > 20:
        raise HTTPException(status_code=422, detail="kind không hợp lệ.")
    now = _utcnow()
    await session.execute(
        pg_insert(WorkerHeartbeat)
        .values(
            worker_id=worker_id,
            kind=kind,
            last_seen=now,
            current_job_id=body.current_job_id,
        )
        .on_conflict_do_update(
            index_elements=[WorkerHeartbeat.worker_id],
            set_={"kind": kind, "last_seen": now,
                  "current_job_id": body.current_job_id},
        )
    )
    await session.commit()
    return {"last_seen": now.isoformat()}

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
                Job.status == "extracting",
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
        job.status != "extracting"
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
                Job.status == "extracting",
                Job.lease_expires_at > now,
                Job.worker_token == token,
            )
            .values(
                status="failed",
                failed_step="extracting",
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

# --- Delete: DELETE /api/jobs/{id} (spec wave-2 #1 — GDPR xóa job) ----------

@router.delete("/api/jobs/{id}", status_code=204)
async def delete_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Owner-or-admin (spec 2026-10-14 #1): xóa HẾT data cá nhân của job —
    derived prefixes exports/{id}/ (md/docx/layout) + crops/{id}/ + version
    objects versions/{id}/, version rows, input object (job.storage_key),
    row. Giữ nguyên contract cancel: job đang extracting/rendering VẪN xóa
    được — ingest guard "job gone → drop" và worker /result|/fail 404 đã có;
    rendering hủy live auto-output task (cancel pattern). Quota SUM realtime
    (page_count count lại từ đầu). Storage lỗi → 500, row còn (retry được)."""
    from app.services import job_results  # lazy: append-only region (R2 lane)

    job = await _job_or_403(session, id, user)
    if job.status == "rendering":
        task = job_results._active_outputs.get(id)
        if task is not None and not task.done():
            task.cancel()
    input_key = job.storage_key
    await storage.delete_prefix(f"exports/{id}/")
    await storage.delete_prefix(f"crops/{id}/")
    await storage.delete_prefix(f"versions/{id}/")
    if input_key:
        # review r1 P1-1: input content-addressed dùng chung (2 job cùng sha)
        # → chỉ xóa object khi KHÔNG job nào khác còn trỏ storage_key này.
        others = (
            await session.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.storage_key == input_key, Job.id != id)
            )
        ).scalar_one()
        if others == 0:
            await storage.delete_prefix(input_key)
    await session.execute(
        delete(DocumentVersion).where(DocumentVersion.job_id == id)
    )
    # review r1 P2: không để heartbeat trỏ job đã xóa (row giữ, upsert tự sửa)
    await session.execute(
        update(WorkerHeartbeat)
        .where(WorkerHeartbeat.current_job_id == id)
        .values(current_job_id=None)
    )
    await session.delete(job)
    await session.commit()
    return Response(status_code=204)

# --- Cancel: POST /api/jobs/{id}/cancel (Hủy job) ---------------------------

@router.post("/api/jobs/{id}/cancel", status_code=204)
async def cancel_job(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Owner cancel, owner-strict (retry pattern): queued|extracting|
    rendering → cancelled (terminal); done|failed|cancelled → 409
    "Không hủy được". extracting also NULLs kaggle_ref so a restart never
    re-adopts the batch run for this job; rendering cancels the live
    auto-output task (job_results._active_outputs). The cancelled row is
    inert everywhere else: ingest/sweep/reaper WHERE guards only match
    queued/extracting/rendering, and the auto-output completion UPDATE is
    WHERE status IN (rendering, failed)."""
    from app.services import job_results  # lazy: append-only region (R2 lane)

    job = await session.get(Job, id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if job.status not in {"queued", "extracting", "rendering"}:
        raise HTTPException(status_code=409, detail="Không hủy được")
    values: dict = {
        "status": "cancelled",
        "failed_step": None,
        "finished_at": _utcnow(),
    }
    if job.status == "extracting":
        values["kaggle_ref"] = None
    if job.status == "rendering":
        task = job_results._active_outputs.get(id)
        if task is not None and not task.done():
            task.cancel()
    # R16 atomic guard (retry pattern): re-check the phase at commit time —
    # a racing claim/result flips rowcount to 0 → same 409.
    rowcount = (
        await session.execute(
            update(Job).where(Job.id == id, Job.status == job.status).values(**values)
        )
    ).rowcount
    if rowcount == 0:
        raise HTTPException(status_code=409, detail="Không hủy được")
    await session.commit()
    return Response(status_code=204)
