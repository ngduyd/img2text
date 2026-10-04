"""Admin routers: users (list + ocr_enabled PATCH), stats, request-log
filter + safe tail. Job retry lives in jobs.py (POST /api/jobs/{id}/retry).
"""

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictBool
from sqlalchemy import Date, Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import get_current_user, require_admin
from app.models import Job, PageView, RequestLog, Setting, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

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
    return {"items": [_user_json(u) for u in rows], "total": total}

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

    days: list[dict] = []
    cur = start
    while cur <= end:
        u = (users.get(cur) or (0,))[0]
        j = jobs.get(cur) or (0, 0, 0, 0.0)
        v = (views.get(cur) or (0,))[0]
        gpu = float(j[3])
        days.append({
            "date": cur.isoformat(),
            "users_registered": u,
            "jobs_submitted": j[0],
            "jobs_done": int(j[1]),
            "jobs_failed": int(j[2]),
            "page_views": v,
            "gpu_seconds": gpu,
            "estimated_cost_usd": round(gpu / 3600 * rate, 4),
        })
        cur += timedelta(days=1)
    return {"days": days}
