"""Admin routers (Task 1 user list + ocr grant; Task 2 stats)."""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictBool
from sqlalchemy import Date, Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_admin
from app.models import Job, PageView, Setting, User

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
