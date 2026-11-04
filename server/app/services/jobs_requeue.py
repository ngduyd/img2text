"""Plan B: lease reaper — requeue extracting jobs whose lease expired.

Started-at reset is deliberate: a reclaimed job's clock must be honest
(error/result fields untouched). Brief Task 5. spec 2026-10-09: the phase
is "extracting" (both HTTP claim and batch spawn set it; "running" gone).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, update

from app.core.config import settings
from app.core.models import Job
from app.services import job_results

logger = logging.getLogger(__name__)

# P1: a rendering job this old with no live in-process task lost its
# fire-and-forget completion (server death mid auto_generate_output).
_STALE_RENDERING = timedelta(minutes=5)

async def reap_leases(session) -> int:
    """Requeue expired-lease extracting jobs; returns rows requeued.

    Covers both claim paths: HTTP-claimed (worker_token_hash set) and batch
    (kaggle_ref set); a queued job never carries a lease, untouched.

    Spec 2026-11-04 (B3): MỘT UPDATE — attempts+1 và CASE quyết định
    queued vs failed khi chạm job_max_attempts (job độc không lặp vô hạn).
    """
    exhausted = Job.attempts + 1 >= settings.job_max_attempts
    result = await session.execute(
        update(Job)
        .where(
            Job.status == "extracting",
            Job.lease_expires_at < func.now(),
        )
        .values(
            attempts=Job.attempts + 1,
            status=case((exhausted, "failed"), else_="queued"),
            error=case(
                (
                    exhausted,
                    "Worker không phản hồi (hết hạn lease) — bấm Thử lại để "
                    f"chạy lại (tối đa {settings.job_max_attempts} lần).",
                ),
                else_=Job.error,
            ),
            worker_token_hash=None,
            lease_expires_at=None,
            started_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    # Core UPDATE + CASE: ORM không tự cập nhật object trong identity map →
    # expire để lần đọc sau thấy giá trị thật (attempts/status/error).
    session.expire_all()
    if result.rowcount:
        logger.info("reap-leases: requeued %d expired lease(s)", result.rowcount)
    return result.rowcount

async def sweep_rendering(session, storage) -> int:
    """P1: re-schedule auto-output for jobs stuck in "rendering" with no
    live task (task died with the process; started_at is the last phase
    marker, so older than _STALE_RENDERING = stuck). Returns tasks started.

    WS-SERVER queue: thêm nhánh rerender_requested — job stuck rendering
    HOẶC đã done nhưng còn cờ (save khi rendering / sync targeted-fail) →
    cũng reschedule; _auto_output claim cờ trước render.

    In-process registry (_active_outputs) owns the one-task-per-job guard;
    the sweep never double-schedules a live render."""
    stale = (
        await session.execute(
            select(Job).where(
                or_(
                    and_(
                        Job.status == "rendering",
                        # started_at IS NULL = batch ingest từ queued (không qua
                        # claim) — cũng phải sweep, SQL NULL < cutoff never true
                        Job.started_at.is_(None)
                        | (
                            Job.started_at
                            < datetime.now(timezone.utc) - _STALE_RENDERING
                        ),
                    ),
                    and_(
                        Job.rerender_requested.is_(True),
                        Job.status.in_(("rendering", "done")),
                    ),
                )
            )
        )
    ).scalars().all()
    n = 0
    for job in stale:
        task = job_results._active_outputs.get(job.id)
        if task is not None and not task.done():
            continue  # live render — not stale
        logger.warning(
            "sweep-rendering: job %s stuck in rendering — reschedule auto "
            "output", job.id,
        )
        job_results._schedule_auto_output(job, storage)
        n += 1
    return n
