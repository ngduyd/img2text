"""Wave-5 S1: purge file gốc (binary only — GIỮ layout/crops/versions/row).

Batch scheduler (`purge-storage`, hourly) + user opt-in endpoint dùng chung
`purge_binary()`. Ruling: chỉ status done; auto_purge per-user; cờ duy nhất
= storage_purged_at (idempotent — WHERE IS NULL). Content-addressed input
dedupe: object chỉ xóa khi KHÔNG job nào khác còn trỏ (delete_job pattern,
mở rộng: job đã purge cũng không tính reference).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models import Job, Setting, User
from app.services.storage import StorageDriver

async def purge_retention_days(session: AsyncSession) -> int:
    """purge_retention_days: Setting override (mirror scheduler tick) else env.
Lane ST: dùng chung cho admin storage tab + user purge-storage-due."""
    row = await session.get(Setting, "purge_retention_days")
    if row is None:
        return settings.purge_retention_days
    try:
        return max(1, int(row.value))
    except (TypeError, ValueError):
        return settings.purge_retention_days


async def purge_binary(
    session: AsyncSession, storage: StorageDriver, job: Job
) -> None:
    """Xóa upload object + 2 export regen được (pdf, docx binary); GIỮ
    crops, md-layout, docx.html, versions, job row. Caller commit."""
    key = job.storage_key
    if key:
        others = (
            await session.execute(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.storage_key == key,
                    Job.id != job.id,
                    Job.storage_purged_at.is_(None),
                )
            )
        ).scalar_one()
        if others == 0:
            await storage.delete_key(key)
    await storage.delete_prefix(f"exports/{job.id}/pdf")
    # EXACT key: prefix delete "exports/{id}/docx" would eat docx.html
    # (GIỮ theo spec) + docx-layout.
    await storage.delete_key(f"exports/{job.id}/docx")
    job.storage_purged_at = datetime.now(timezone.utc)


async def purge_due_jobs(
    session: AsyncSession,
    storage: StorageDriver,
    retention_days: int,
    limit: int = 200,
    user_id: int | None = None,
) -> int:
    """Batch: done + cũ hơn retention + auto_purge + chưa purge → purge.
    limit = mỗi tick (batch nhỏ, tick kế tiếp quét tiếp — ponytail:
    upgrade sang cursor pagination khi user có >limit job đến hạn).
    user_id (Lane ST): scope về 1 user — user tự dọn storage của mình."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    rows = (
        (
            await session.execute(
                select(Job)
                .join(User, User.id == Job.user_id)
                .where(
                    Job.status == "done",
                    Job.created_at < cutoff,
                    Job.storage_purged_at.is_(None),
                    # NULL legacy = không chắc chắn → không purge (an toàn)
                    User.auto_purge.is_(True),
                    *([Job.user_id == user_id] if user_id is not None else []),
                )
                .order_by(Job.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for job in rows:
        await purge_binary(session, storage, job)
    await session.commit()
    return len(rows)
