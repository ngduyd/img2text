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
# Wave-5 S1: quota bytes upload 7 ngày rolling — legacy NULL → 202MB
UPLOAD_BYTE_DEFAULT = 211_812_352
UPLOAD_WINDOW = timedelta(days=7)

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

# --- Wave-5 S1: quota bytes upload 7 ngày rolling ---
#
# Window = created_at > now-7d AND upload_bytes>0 (spec: SUM upload_bytes).
# Refund = transition point set upload_bytes=0 (failed/cancelled) — KHÔNG
# exclude status ở đây (khác page quota): bytes ghi thật lúc create.

def _bytes_cutoff(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)) - UPLOAD_WINDOW

async def bytes_usage(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> int:
    """SUM(upload_bytes) trong cửa sổ 7 ngày; row refund (0) tự loại."""
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(Job.upload_bytes), 0)).where(
                Job.user_id == user_id,
                Job.created_at > _bytes_cutoff(now),
                Job.upload_bytes > 0,
            )
        )
    )

async def bytes_oldest_expires_at(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> datetime | None:
    """created_at sớm nhất trong cửa sổ + 7d = thời điểm bytes trôi ra
    (429 payload oldest_expires_at). Cửa sổ trống → None."""
    oldest = await session.scalar(
        select(func.min(Job.created_at)).where(
            Job.user_id == user_id,
            Job.created_at > _bytes_cutoff(now),
            Job.upload_bytes > 0,
        )
    )
    return None if oldest is None else oldest + UPLOAD_WINDOW

async def ensure_bytes_quota(
    session: AsyncSession, user: User, incoming_bytes: int
) -> None:
    """Pre-create gate bytes (spec S1): used + mới > limit → 429 structured
    {code, used_bytes, limit_bytes, oldest_expires_at} — reject, KHÔNG
    auto-evict (ruling). Presign chưa có bytes thật → gate tại POST /api/jobs."""
    limit = limit_of(user.upload_byte_limit, UPLOAD_BYTE_DEFAULT)
    used = await bytes_usage(session, user.id)
    if used + incoming_bytes > limit:
        oldest = await bytes_oldest_expires_at(session, user.id)
        raise HTTPException(
            status_code=429,
            detail={
                "code": "upload_quota",
                "used_bytes": used,
                "limit_bytes": limit,
                "oldest_expires_at": (
                    oldest.isoformat() if oldest else None
                ),
            },
        )

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
    """GET /api/quota/me — remaining clamped ≥ 0 (đã vượt thì về 0).
    Wave-5 S1: thêm số liệu bytes 7 ngày (web quota badge)."""
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
        # wave-5 S1
        "upload_used_bytes": await bytes_usage(session, user.id),
        "upload_limit_bytes": limit_of(
            user.upload_byte_limit, UPLOAD_BYTE_DEFAULT
        ),
    }
