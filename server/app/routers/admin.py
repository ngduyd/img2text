"""Admin routers: users (list + ocr_enabled PATCH), stats, request-log
filter + safe tail. Job retry lives in jobs.py (POST /api/jobs/{id}/retry).
"""

import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from time import perf_counter

import httpx
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt
from sqlalchemy import Date, Float, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, require_admin
from app.core.models import (
    EmailSend,
    Job,
    PageView,
    RequestLog,
    Setting,
    User,
    WorkerHeartbeat,
)
from app.routers.auth import revoke_all_refresh
from app.services.kaggle_quota import kaggle_quota_payload
from app.services.purge import purge_due_jobs, purge_retention_days
from app.services.runtime_settings import (
    RUNTIME_SETTING_KEYS,
    get_runtime_setting,
    get_runtime_setting_entry,
)
from app.services.storage import StorageDriver, get_storage
from app.services.quota import (
    DAILY_DEFAULT,
    WEEKLY_DEFAULT,
    daily_window,
    limit_of,
    usage_map,
    weekly_window,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

logger = logging.getLogger(__name__)

def _admin_user(user: User = Depends(get_current_user)) -> User:
    return require_admin(user)

class OcrPatch(BaseModel):
    ocr_enabled: StrictBool  # StrictBool: "yes" must 422, not coerce to True

def _user_json(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "ocr_enabled": u.ocr_enabled,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }

@router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
    page: int = 1,
    size: int = 20,
) -> dict:
    """Paged user list, id asc.

    ponytail: out-of-bounds paging CLAMPED (page≥1, 1≤size≤100) per task choice;
    switch to 422 Query(ge=..., le=...) if API strictness is ever required.
    """
    page = max(1, page)
    size = min(100, max(1, size))
    total = (await session.scalar(select(func.count()).select_from(User))) or 0
    rows = (
        await session.scalars(
            select(User).order_by(User.id).offset((page - 1) * size).limit(size)
        )
    ).all()
    # WS-ADMIN T5: quota per user (1 query/window thay vì N)
    ids = [u.id for u in rows]
    daily_used = await usage_map(session, ids, daily_window())
    weekly_used = await usage_map(session, ids, weekly_window())
    items = []
    for u in rows:
        d, w = daily_used.get(u.id, 0), weekly_used.get(u.id, 0)
        dl = limit_of(u.daily_page_limit, DAILY_DEFAULT)
        wl = limit_of(u.weekly_page_limit, WEEKLY_DEFAULT)
        items.append({
            **_user_json(u),
            "daily_limit": dl,
            "daily_used": d,
            "daily_remaining": max(dl - d, 0),
            "weekly_limit": wl,
            "weekly_used": w,
            "weekly_remaining": max(wl - w, 0),
        })
    return {"items": items, "total": total}

def _silent_seconds(last_seen: datetime, now: datetime) -> int:
    """review r1 P2: last_seen naive → coi UTC (legacy row); clamp 0 khi
    last_seen ở tương lai (clock skew) — card web không thấy số âm."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return max(0, int((now - last_seen).total_seconds()))

@router.get("/workers")
async def list_workers(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """wave-2 #7: heartbeat rows + silent_seconds (derived) + queue_depth.
    Admin card "Workers" badge im lặng > 2 lease (web tự tính từ silent_seconds)."""
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc())
        )
    ).scalars().all()
    queue_depth = (
        await session.scalar(select(func.count()).where(Job.status == "queued"))
    ) or 0
    return {
        "items": [
            {
                "worker_id": r.worker_id,
                "kind": r.kind,
                "last_seen": r.last_seen.isoformat(),  # RFC3339 string (pin)
                "current_job_id": r.current_job_id,
                "silent_seconds": _silent_seconds(r.last_seen, now),
            }
            for r in rows
        ],
        "queue_depth": queue_depth,
    }

class QuotaPatch(BaseModel):
    # StrictInt: "5" must 422 (không coerce); range check → detail VN dưới đây
    daily_page_limit: StrictInt
    weekly_page_limit: StrictInt

@router.patch("/users/{user_id}/quota", status_code=204)
async def patch_user_quota(
    user_id: int,
    body: QuotaPatch,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> None:
    """Inline edit 2 ô limit (admin UI T5) — 204 no body."""
    if not (0 <= body.daily_page_limit <= 10000 and 0 <= body.weekly_page_limit <= 10000):
        raise HTTPException(
            status_code=422,
            detail="Giới hạn trang phải trong khoảng 0–10000.",
        )
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.daily_page_limit = body.daily_page_limit
    user.weekly_page_limit = body.weekly_page_limit
    await session.commit()

@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: OcrPatch,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.ocr_enabled = body.ocr_enabled
    await session.commit()
    return _user_json(user)

@router.post("/users/{user_id}/revoke-sessions", status_code=204)
async def admin_revoke_sessions(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(_admin_user),
) -> None:
    """P2 #17 (spec 2026-10-16): admin thu hồi MỌI refresh token của target
    user (compromised account → kill family ngay). 204 no body; audit =
    logger line (ai thu hồi, target nào) + RequestLog middleware row."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await revoke_all_refresh(session, user_id)
    logger.info(
        "audit: admin %s revoked all sessions for user %s", admin.id, user_id
    )

async def get_usd_per_gpu_hour(session: AsyncSession) -> float:
    """Setting key usd_per_gpu_hour as float; 0.0 on missing/bad parse."""
    row = await session.get(Setting, "usd_per_gpu_hour")
    if row is None:
        return 0.0
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return 0.0

async def _grouped(
    session: AsyncSession, model, date_col, where, extra: dict | None = None
) -> dict[date, tuple]:
    """Count (plus optional aggregate columns) per UTC calendar day."""
    day = cast(date_col, Date)
    stmt = (
        select(day, func.count(), *(extra or {}).values())
        .where(*where)
        .group_by(day)
    )
    return {r[0]: r[1:] for r in (await session.execute(stmt)).all()}

def _log_json(r: RequestLog) -> dict:
    return {
        "id": r.id,
        "ts": r.ts.isoformat() if r.ts else None,
        "method": r.method,
        "path": r.path,
        "status": r.status,
        "user_id": r.user_id,
        "ip": r.ip,
        "ua": r.ua,
    }

@router.get("/logs")
async def list_logs(
    status_class: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """RequestLog newest first; status_class in 2xx|4xx|5xx; limit clamp 1..500.

    ponytail: unknown status_class value = no status filter (ignore, not 422).
    """
    limit = min(500, max(1, limit))
    stmt = select(RequestLog).order_by(RequestLog.ts.desc())
    bands = {"2xx": (200, 299), "4xx": (400, 499), "5xx": (500, 599)}
    if status_class in bands:
        lo, hi = bands[status_class]
        stmt = stmt.where(RequestLog.status.between(lo, hi))
    if ip is not None:
        stmt = stmt.where(RequestLog.ip == ip)
    rows = (await session.scalars(stmt.limit(limit))).all()
    return {"items": [_log_json(r) for r in rows]}

@router.get("/logs/tail")
async def tail_logs(
    lines: int = 200,
    _: User = Depends(_admin_user),
) -> dict:
    """Last N lines of app log; path from Settings ONLY (no path query param —
    traversal impossible by construction); lines clamp 1..500; missing file = [].

    ponytail: whole-file read + splitlines tail; fine for modest admin logs;
    switch to seek-from-end binary tail if files grow huge.
    """
    lines = min(500, max(1, lines))
    path = Path(settings.log_path)
    if not path.exists():
        return {"lines": []}
    text = await asyncio.to_thread(path.read_text)
    return {"lines": text.splitlines()[-lines:]}

@router.get("/stats")
async def stats(
    date_from: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """Per-day activity + gpu cost estimate; dates inclusive, UTC days.

    Default window: last 7 days (to=today). Gap days zero-filled.
    emails_sent/emails_failed = ledger email theo ngày; emails_stuck = row còn
    queued quá due 15' (drain job chết) hoặc row sending đã hết lease
    (next_attempt_at là lease deadline khi đang gửi → crash giữa send).
    """
    today = datetime.now(timezone.utc).date()
    end = to or today
    start = date_from or end - timedelta(days=6)
    if start > end:
        raise HTTPException(status_code=422, detail="from must be <= to")
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    rate = await get_usd_per_gpu_hour(session)
    users = await _grouped(session, User, User.created_at,
                           (User.created_at >= lo, User.created_at < hi))
    jobs = await _grouped(
        session, Job, Job.created_at,
        (Job.created_at >= lo, Job.created_at < hi),
        {
            "done": func.sum(case((Job.status == "done", 1), else_=0)),
            "failed": func.sum(case((Job.status == "failed", 1), else_=0)),
            "gpu": func.coalesce(
                func.sum(case(
                    (Job.status == "done",
                     func.cast(Job.result["gpu_seconds"].astext, Float)),
                    else_=0.0,
                )),
                0.0,
            ),
        },
    )
    views = await _grouped(session, PageView, PageView.created_at,
                           (PageView.created_at >= lo, PageView.created_at < hi))
    emails = await _grouped(
        session, EmailSend, EmailSend.created_at,
        (EmailSend.created_at >= lo, EmailSend.created_at < hi),
        {
            "sent": func.sum(case((EmailSend.status == "sent", 1), else_=0)),
            "failed": func.sum(case((EmailSend.status == "failed", 1), else_=0)),
        },
    )
    now = datetime.now(timezone.utc)
    emails_stuck = (
        await session.scalar(
            select(func.count())
            .select_from(EmailSend)
            .where(
                or_(
                    and_(
                        EmailSend.status == "queued",
                        EmailSend.next_attempt_at < now - timedelta(minutes=15),
                    ),
                    and_(
                        EmailSend.status == "sending",
                        EmailSend.next_attempt_at < now,  # lease hết hạn
                    ),
                )
            )
        )
    ) or 0

    days: list[dict] = []
    cur = start
    while cur <= end:
        u = (users.get(cur) or (0,))[0]
        j = jobs.get(cur) or (0, 0, 0, 0.0)
        v = (views.get(cur) or (0,))[0]
        e = emails.get(cur) or (0, 0, 0)
        gpu = float(j[3])
        days.append({
            "date": cur.isoformat(),
            "users_registered": u,
            "jobs_submitted": j[0],
            "jobs_done": int(j[1]),
            "jobs_failed": int(j[2]),
            "page_views": v,
            "emails_sent": int(e[1]),
            "emails_failed": int(e[2]),
            "gpu_seconds": gpu,
            "estimated_cost_usd": round(gpu / 3600 * rate, 4),
        })
        cur += timedelta(days=1)
    return {"days": days, "emails_stuck": int(emails_stuck)}

# --- Lane K: Kaggle GPU/TPU quota (admin card) ---
# Parse + HTTP mapping (503/502, response shape) tách
# app/services/kaggle_quota.py (spec session worker T8, AC6) — orchestrator
# dispatch gate dùng chung field-mapping; pin test_admin_kaggle_quota giữ.

@router.get("/kaggle-quota")
def kaggle_quota(_: User = Depends(_admin_user)) -> dict:
    """Lane K: quota GPU/TPU hiện tại từ Kaggle. sync def → threadpool
    (quota_view() network call chặn event loop nếu chạy async)."""
    return kaggle_quota_payload()

# --- Lane B3 (S4): admin storage-cleanup page ---
# retention helper sống ở app.services.purge (dùng chung với user purge-due).

@router.get("/storage")
async def admin_storage(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
    page: int = 1,
    size: int = 20,
) -> dict:
    """Lane B3: stats dung lượng + list jobs cũ (created_at < cutoff) paged.

    due_jobs = đúng predicate purge batch (done + auto_purge + chưa purge) —
    số việc POST purge-due sẽ thật sự làm. Page clamp mirror list_users.
    """
    page = max(1, page)
    size = min(100, max(1, size))
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=await purge_retention_days(session)
    )
    total_jobs = (await session.scalar(select(func.count()).select_from(Job))) or 0
    purged_jobs = (
        await session.scalar(
            select(func.count()).where(Job.storage_purged_at.is_not(None))
        )
    ) or 0
    total_upload_bytes = int(
        await session.scalar(select(func.coalesce(func.sum(Job.upload_bytes), 0)))
        or 0
    )
    purged_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(Job.upload_bytes), 0)).where(
                Job.storage_purged_at.is_not(None)
            )
        )
        or 0
    )
    due_jobs = (
        await session.scalar(
            select(func.count())
            .select_from(Job)
            .join(User, User.id == Job.user_id)
            .where(
                Job.status == "done",
                Job.created_at < cutoff,
                Job.storage_purged_at.is_(None),
                User.auto_purge.is_(True),
            )
        )
    ) or 0
    old = (
        await session.execute(
            select(Job, User.email, User.auto_purge)
            .join(User, User.id == Job.user_id)
            .where(Job.created_at < cutoff)
            .order_by(Job.created_at, Job.id)
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    total_old = (
        await session.scalar(
            select(func.count()).select_from(Job).where(Job.created_at < cutoff)
        )
    ) or 0
    return {
        "stats": {
            "total_jobs": total_jobs,
            "purged_jobs": purged_jobs,
            "due_jobs": due_jobs,
            "total_upload_bytes": total_upload_bytes,
            "purged_bytes": purged_bytes,
        },
        "items": [
            {
                "id": j.id,
                "email": email,
                "filename": j.filename,
                "upload_bytes": j.upload_bytes,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "storage_purged_at": (
                    j.storage_purged_at.isoformat() if j.storage_purged_at else None
                ),
                "auto_purge": auto_purge,
            }
            for j, email, auto_purge in old
        ],
        "total": total_old,
    }

@router.post("/storage/purge-due")
async def admin_storage_purge_due(
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
    _: User = Depends(_admin_user),
) -> dict:
    """Lane B3: chạy purge_due_jobs NGAY (cùng retention + batch limit với
    scheduler tick) — {purged: n}. purge_due_jobs tự commit."""
    n = await purge_due_jobs(session, storage, await purge_retention_days(session))
    return {"purged": n}

# --- Plan S: runtime settings (admin live tuning, scheduler/kaggle) ---

# Floors: R58a (no busy-loop) + minimum queue/gap sanity.
_SETTING_FLOORS: dict[str, tuple[int, str]] = {
    "scheduler_interval_seconds": (
        5, "scheduler_interval_seconds phải từ 5 giây trở lên.",
    ),
    # wave-5 S1: purge tick floor 60s (busy-loop guard), retention ≥ 1 ngày
    "purge_interval_seconds": (
        60, "purge_interval_seconds phải từ 60 giây trở lên.",
    ),
    "purge_retention_days": (
        1, "purge_retention_days phải từ 1 ngày trở lên.",
    ),
    "kaggle_min_queue": (1, "kaggle_min_queue phải từ 1 trở lên."),
    "kaggle_min_gap_seconds": (
        60, "kaggle_min_gap_seconds phải từ 60 giây trở lên.",
    ),
    # Lane CFG: floors (smtp_port ceiling 65535 checked separately below)
    "smtp_port": (1, "smtp_port phải trong khoảng 1–65535."),
    "max_pages": (1, "max_pages phải từ 1 trở lên."),
    "upload_byte_limit": (
        1_048_576, "upload_byte_limit phải từ 1MB trở lên.",
    ),
    # P2b: quota floors ≥0 (âm = giá trị vô nghĩa, không được silent accept)
    "daily_page_limit": (0, "daily_page_limit phải từ 0 trở lên."),
    "weekly_page_limit": (0, "weekly_page_limit phải từ 0 trở lên."),
}

class RuntimeSettingsPut(BaseModel):
    # rider: unknown keys 422 — typo'd key must not silently no-op a PUT
    model_config = ConfigDict(extra="forbid")

    scheduler_interval_seconds: int | None = None
    purge_interval_seconds: int | None = None
    purge_retention_days: int | None = None
    kaggle_min_queue: int | None = None
    kaggle_min_gap_seconds: int | None = None
    # read-only in the API — mode flip needs a restart (half-applied state)
    kaggle_mode: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    proofread_llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout: int | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_pass: str | None = None
    smtp_from: str | None = None
    max_pages: int | None = None
    daily_page_limit: int | None = None
    weekly_page_limit: int | None = None
    upload_byte_limit: int | None = None

# Write-only keys: masked in responses, empty PUT = keep existing value.
_WRITE_ONLY_KEYS = ("llm_api_key", "smtp_pass")

def _mask_api_key(value) -> str | None:
    """WS-ADMIN write-only: "sk-…last4" (or "***" short), empty → null.
    Full key stays in the Setting row — render/proofread read it directly;
    never echoed in a response (and never logged: middleware logs no body)."""
    if not value:
        return None
    s = str(value)
    return f"{s[:3]}…{s[-4:]}" if len(s) >= 8 else "***"

async def _runtime_settings(session_factory) -> dict:
    out = {
        key: await get_runtime_setting_entry(session_factory, key)
        for key in RUNTIME_SETTING_KEYS
    }
    out["llm_api_key"]["value"] = _mask_api_key(out["llm_api_key"]["value"])
    out["smtp_pass"]["value"] = _mask_api_key(out["smtp_pass"]["value"])
    return out

def _reschedule_reap(app, seconds: int) -> bool:
    """Live apply: retarget the reap-leases interval trigger (no restart)."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:  # lifespan not run (tests) — DB row stands for next boot
        return False
    job = scheduler.get_job("reap-leases")
    if job is None:
        return False
    job.reschedule(IntervalTrigger(seconds=seconds))
    return True

@router.get("/settings")
async def get_settings(
    request: Request,
    _: User = Depends(_admin_user),
) -> dict:
    """Effective runtime values per key: {key: {value, source: "db"|"env"}}."""
    return await _runtime_settings(request.app.state.session_factory)

@router.put("/settings")
async def put_settings(
    body: RuntimeSettingsPut,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """Upsert Setting overrides + live reschedule; returns effective values.

    kaggle_mode is read-only here (đổi mode cần restart container — a mid-run
    flip would half-apply batch/loop state). Audit = RequestLog row written by
    RequestLogsMiddleware for this request.
    """
    if body.kaggle_mode is not None:
        raise HTTPException(
            status_code=422,
            detail="kaggle_mode là read-only — thay đổi mode cần restart container.",
        )
    for key, (floor, message) in _SETTING_FLOORS.items():
        value = getattr(body, key)
        if value is not None and value < floor:
            raise HTTPException(status_code=422, detail=message)
    if body.llm_timeout is not None and not 120 <= body.llm_timeout <= 600:
        raise HTTPException(
            status_code=422,
            detail="llm_timeout phải trong khoảng 120–600 giây.",
        )
    if body.smtp_port is not None and body.smtp_port > 65535:
        raise HTTPException(
            status_code=422,
            detail="smtp_port phải trong khoảng 1–65535.",
        )
    for key in _SETTING_FLOORS:
        value = getattr(body, key)
        if value is None:
            continue
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)
    for key in (
        "llm_base_url",
        "llm_model",
        "proofread_llm_model",
        "llm_api_key",
        "llm_timeout",
        "smtp_host",
        "smtp_user",
        "smtp_pass",
        "smtp_from",
        # numeric, no floor — str() upsert matches the llm_timeout precedent
        # (daily/weekly_page_limit chuyển sang _SETTING_FLOORS — P2b)
    ):
        value = getattr(body, key)
        # Lane C: write-only key — form để trống = giữ nguyên (không echo nên
        # client không thể phân biệt "chưa set" vs "muốn xóa").
        if value is None or (key in _WRITE_ONLY_KEYS and not value):
            continue
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)
    await session.commit()
    if body.scheduler_interval_seconds is not None:
        _reschedule_reap(request.app, body.scheduler_interval_seconds)
    return await _runtime_settings(request.app.state.session_factory)

@router.delete("/settings/{key}")
async def delete_setting(
    key: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """Lane CFG reset: xóa Setting row → key lại đọc env default (source
    "env"). Chỉ key runtime — 404 với key lạ (typo không được silent no-op)."""
    if key not in RUNTIME_SETTING_KEYS:
        raise HTTPException(status_code=404, detail=f"unknown setting: {key}")
    row = await session.get(Setting, key)
    if row is not None:
        await session.delete(row)
        await session.commit()
    if key == "scheduler_interval_seconds":
        _reschedule_reap(request.app, settings.scheduler_interval_seconds)
    return await _runtime_settings(request.app.state.session_factory)

class LlmTestModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    base_url: str | None = None

@router.post("/llm/test-model")
async def llm_test_model(
    body: LlmTestModelBody,
    request: Request,
    _: User = Depends(_admin_user),
) -> dict:
    """Lane CFG: probe model sống/chết — 1 prompt \"ping\" (max_tokens 5),
    timeout 15s, KHÔNG persist. base_url: body override, else runtime
    setting. Trả {ok, latency_ms, model, error} — ok luôn trong response 200
    (lỗi LLM nằm ở `error`, client không cần phân biệt status)."""
    session_factory = request.app.state.session_factory
    base_url = body.base_url or await get_runtime_setting(
        session_factory, "llm_base_url", settings.llm_base_url
    )
    api_key = await get_runtime_setting(session_factory, "llm_api_key")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": body.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }
    started = perf_counter()
    try:
        async with AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=15)
    except httpx.TimeoutException:
        return {
            "ok": False,
            "latency_ms": int((perf_counter() - started) * 1000),
            "model": body.model,
            "error": "timeout sau 15s",
        }
    except Exception as exc:
        # P1 contract: 1 nhánh catch-all (httpx.HTTPError, InvalidURL từ base_url
        # hỏng, …) → 200 {ok:false, error}; client không cần phân biệt status.
        return {
            "ok": False,
            "latency_ms": int((perf_counter() - started) * 1000),
            "model": body.model,
            "error": f"{type(exc).__name__}: {exc}",
        }
    latency_ms = int((perf_counter() - started) * 1000)
    if resp.status_code != 200:
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "model": body.model,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    return {"ok": True, "latency_ms": latency_ms, "model": body.model, "error": None}
