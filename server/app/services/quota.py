"""WS-ADMIN quota (spec 2026-10-13 item 19): usage = SUM(jobs.page_count)
trong cửa sổ — ngày theo local Asia/Ho_Chi_Minh, tuần T2→CN (local) —
status NOT IN ('failed','cancelled') (job fail = hoàn quota).

Check tại pre-create (presign + POST /api/jobs) → 429; GET /api/quota/me
đọc số cho widget Jobs. Sessions từ deps (mọi caller async — không to_thread).
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Job, User

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
EXCLUDED_STATUSES = ("failed", "cancelled")
# Fallback khi cột legacy NULL (ALTER-only migration không backfill model)
DAILY_DEFAULT = 25
WEEKLY_DEFAULT = 150

def limit_of(value: int | None, default: int) -> int:
    return default if value is None else value

def _local_now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)

def daily_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """[00:00, 00:00) ngày `now` theo local, trả về UTC (so sánh created_at)."""
    start = datetime.combine(_local_now(now).date(), time.min, tzinfo=LOCAL_TZ)
    return (
        start.astimezone(timezone.utc),
        (start + timedelta(days=1)).astimezone(timezone.utc),
    )

def weekly_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Tuần local T2→CN: [00:00 T2, 00:00 T2 kế)."""
    local = _local_now(now)
    start = datetime.combine(
        local.date() - timedelta(days=local.weekday()), time.min, tzinfo=LOCAL_TZ
    )
    return (
        start.astimezone(timezone.utc),
        (start + timedelta(days=7)).astimezone(timezone.utc),
    )

def _usage_stmt(user_id: int, window: tuple[datetime, datetime]):
    lo, hi = window
    return (
        select(func.coalesce(func.sum(Job.page_count), 0))
        .where(
            Job.user_id == user_id,
            Job.status.notin_(EXCLUDED_STATUSES),
            Job.created_at >= lo,
            Job.created_at < hi,
        )
    )

async def usage(
    session: AsyncSession, user_id: int, window: tuple[datetime, datetime]
) -> int:
    return int(await session.scalar(_usage_stmt(user_id, window)))

async def usage_map(
    session: AsyncSession, user_ids: list[int], window: tuple[datetime, datetime]
) -> dict[int, int]:
    """SUM(page_count) per user (admin bảng quota) — 1 query cho cả list."""
    lo, hi = window
    rows = await session.execute(
        select(Job.user_id, func.coalesce(func.sum(Job.page_count), 0))
        .where(
            Job.user_id.in_(user_ids),
            Job.status.notin_(EXCLUDED_STATUSES),
            Job.created_at >= lo,
            Job.created_at < hi,
        )
        .group_by(Job.user_id)
    )
    return {int(uid): int(total) for uid, total in rows}

async def ensure_quota(
    session: AsyncSession, user: User, incoming_pages: int | None
) -> None:
    """Pre-create gate → 429 khi vượt ngày/trước. incoming_pages=None (presign
    chưa đếm trang) → coi như 1 trang; POST /api/jobs truyền page_count thật."""
    pages = incoming_pages if incoming_pages is not None else 1
    daily = limit_of(user.daily_page_limit, DAILY_DEFAULT)
    weekly = limit_of(user.weekly_page_limit, WEEKLY_DEFAULT)
    if await usage(session, user.id, daily_window()) + pages > daily:
        raise HTTPException(
            status_code=429,
            detail=f"Hôm nay bạn đã hết quota ({daily} trang). Quay lại sau.",
        )
    if await usage(session, user.id, weekly_window()) + pages > weekly:
        raise HTTPException(
            status_code=429,
            detail=f"Tuần này bạn đã hết quota ({weekly} trang). Quay lại sau.",
        )

async def quota_me(session: AsyncSession, user: User) -> dict:
    """GET /api/quota/me — remaining clamped ≥ 0 (đã vượt thì về 0)."""
    daily = limit_of(user.daily_page_limit, DAILY_DEFAULT)
    weekly = limit_of(user.weekly_page_limit, WEEKLY_DEFAULT)
    daily_used = await usage(session, user.id, daily_window())
    weekly_used = await usage(session, user.id, weekly_window())
    return {
        "daily_limit": daily,
        "daily_used": daily_used,
        "weekly_limit": weekly,
        "weekly_used": weekly_used,
        "daily_remaining": max(daily - daily_used, 0),
        "weekly_remaining": max(weekly - weekly_used, 0),
    }
