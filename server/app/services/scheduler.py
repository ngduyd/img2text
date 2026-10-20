"""Background scheduler (Task 8).

ponytail: brief names apscheduler 4.x `AsyncScheduler`; package mirror has no
stable 4.x (only alphas), so this uses stable 3.x `AsyncIOScheduler` with the
same jobs. Upgrade to AsyncScheduler when 4.x is stable on the mirror.
R58a: server-side upload kick was deleted (reaper ≠ claim); fresh queued
jobs are claimed by workers polling GET /api/jobs/next, the sweep loop only
requeues expired leases.
"""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from app.core.config import settings
from app.services.kaggle_orchestrator import ensure_worker
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger(__name__)

async def _run_jobs_once(storage) -> None:
    """One claim pass: requeue expired leases (only server-side job advance;
    fresh queued jobs are claimed by workers polling GET /api/jobs/next) +
    P1 sweep of stale rendering jobs."""
    from app.core.db import SessionLocal
    from app.services.jobs_requeue import reap_leases, sweep_rendering

    async with SessionLocal() as session:
        n = await reap_leases(session)
        m = await sweep_rendering(session, storage)
    logger.info("reap-leases: requeued %d; sweep-rendering: %d", n, m)


def init_scheduler(app: FastAPI) -> AsyncIOScheduler:
    """Register jobs; store on app.state.scheduler. Start() skipped under
    pytest (PYTEST_CURRENT_TEST) so tests stay quiet; prod wiring (lifespan)
    starts it unconditionally."""
    scheduler = AsyncIOScheduler()

    async def reap_all() -> None:
        # Plan S: per-tick interval override — Setting row wins over env; also
        # re-applies the DB value after a restart (add_job seeds from env only).
        try:
            seconds = max(
                5,
                await get_runtime_setting(
                    app.state.session_factory,
                    "scheduler_interval_seconds",
                    settings.scheduler_interval_seconds,
                ),
            )
            job = scheduler.get_job("reap-leases")
            if job is not None and job.trigger.interval_length != seconds:
                job.reschedule(IntervalTrigger(seconds=seconds))
                logger.info("reap-leases: interval → %ds (runtime override)", seconds)
        except Exception:  # one failing check must not kill the pass
            logger.warning("scheduler interval override check failed", exc_info=True)
        try:
            await _run_jobs_once(app.state.storage)
        except Exception:  # one failing pass must not kill the job
            logger.warning("scheduler claim pass failed", exc_info=True)
        try:
            # Plan K2: auto-spawn Kaggle worker kernel when queue needs it;
            # ensure_worker is disabled-by-default + never raises, this wrap
            # is belt-and-braces for the scheduler job.
            spawned = await ensure_worker(app.state.session_factory)
            if spawned:
                logger.info("kaggle: worker kernel spawned")
        except Exception:  # one failing pass must not kill the job
            logger.warning("kaggle ensure_worker pass failed", exc_info=True)

    scheduler.add_job(
        reap_all,
        trigger="interval",
        seconds=settings.scheduler_interval_seconds,
        id="reap-leases",
    )

    async def prune_all() -> None:
        from app.core.middleware import (
            prune_page_views,
            prune_refresh_tokens,
            prune_request_logs,
        )

        async with app.state.session_factory() as session:
            results: dict[str, int] = {}
            for label, prune in (
                ("request_logs", prune_request_logs),
                ("page_views", prune_page_views),
                ("refresh_tokens", prune_refresh_tokens),
            ):
                try:
                    results[label] = await prune(session)
                except Exception:  # one failing prune must not skip the others
                    logger.exception("daily prune: %s failed", label)
        logger.info(
            "daily prune: request_logs=%s page_views=%s refresh_tokens=%s",
            results.get("request_logs"),
            results.get("page_views"),
            results.get("refresh_tokens"),
        )

    scheduler.add_job(prune_all, trigger="cron", hour=3, minute=0, id="daily-prune")

    async def purge_all() -> None:
        """wave-5 S1: purge file gốc batch — interval/retention đọc runtime
        override mỗi tick (pattern reschedule reap-leases); một pass lỗi
        không giết tick."""
        from app.services.purge import purge_due_jobs

        try:
            seconds = max(
                60,
                await get_runtime_setting(
                    app.state.session_factory,
                    "purge_interval_seconds",
                    settings.purge_interval_seconds,
                ),
            )
            job = scheduler.get_job("purge-storage")
            if job is not None and job.trigger.interval_length != seconds:
                job.reschedule(IntervalTrigger(seconds=seconds))
                logger.info(
                    "purge-storage: interval → %ds (runtime override)", seconds
                )
            retention = max(
                1,
                await get_runtime_setting(
                    app.state.session_factory,
                    "purge_retention_days",
                    settings.purge_retention_days,
                ),
            )
            async with app.state.session_factory() as session:
                n = await purge_due_jobs(session, app.state.storage, retention)
            if n:
                logger.info("purge-storage: purged %d job(s)", n)
        except Exception:
            logger.warning("purge-storage pass failed", exc_info=True)

    scheduler.add_job(
        purge_all,
        trigger="interval",
        seconds=settings.purge_interval_seconds,
        id="purge-storage",
    )
    async def flush_logs() -> None:
        """P2 #18: drain request_logs buffer (bulk insert) mỗi 30s."""
        from app.core.middleware import flush_request_logs

        try:
            n = await flush_request_logs(app)
        except Exception:  # one failing pass must not kill the job
            logger.warning("flush-request-logs failed", exc_info=True)
            return
        if n:
            logger.info("flush-request-logs: %d row(s)", n)

    scheduler.add_job(
        flush_logs, trigger="interval", seconds=30, id="flush-request-logs"
    )

    async def flush_email_outbox() -> None:
        """2026-10-20: drain DB email outbox (route chỉ enqueue).
        ponytail: interval 20s cố định — chưa cần runtime override."""
        from app.core.db import SessionLocal
        from app.services import email_sends

        try:
            async with SessionLocal() as session:
                sent, failed = await email_sends.drain(session)
        except Exception:  # one failing pass must not kill the job
            logger.warning("flush-email-outbox failed", exc_info=True)
            return
        if sent or failed:
            logger.info("flush-email-outbox: sent=%d failed=%d", sent, failed)

    scheduler.add_job(
        flush_email_outbox, trigger="interval", seconds=20, id="flush-email-outbox"
    )

    async def backup_db() -> None:
        """#12: daily pg_dump — cron/retention đọc runtime override mỗi tick
        (pattern reschedule reap-leases); pg_dump chạy to_thread (block I/O)
        và một pass lỗi không giết tick."""
        from app.core.db import backup_database

        cron = settings.backup_cron
        retention: int | None = None
        try:
            cron = await get_runtime_setting(
                app.state.session_factory, "backup_cron", settings.backup_cron
            )
            retention = int(
                await get_runtime_setting(
                    app.state.session_factory,
                    "backup_retention_days",
                    settings.backup_retention_days,
                )
            )
        except Exception:
            logger.warning("backup-db: runtime settings read failed", exc_info=True)
        try:
            trigger = CronTrigger.from_crontab(cron)
            job = scheduler.get_job("backup-db")
            # QA-4: CronTrigger 3.x KHÔNG có __eq__ → `!=` là identity so sánh,
            # luôn True → reschedule vô nghĩa mỗi tick. So sánh bằng str().
            if job is not None and str(job.trigger) != str(trigger):
                job.reschedule(trigger)
                logger.info("backup-db: cron → %s (runtime override)", cron)
        except Exception:
            logger.warning("backup-db: invalid backup_cron %r", cron, exc_info=True)
        try:
            dest = await asyncio.to_thread(backup_database, retention_days=retention)
            logger.info("backup-db: wrote %s", dest)
        except Exception:
            logger.warning("backup-db pass failed", exc_info=True)

    # Cron sai ở env → from_crontab nổ TẠI ĐÂY = fail-fast boot (misconfig
    # phải ồn ào, không âm thầm không backup bao giờ).
    scheduler.add_job(
        backup_db,
        trigger=CronTrigger.from_crontab(settings.backup_cron),
        id="backup-db",
    )
    app.state.scheduler = scheduler
    if "PYTEST_CURRENT_TEST" not in os.environ:
        scheduler.start()
    return scheduler
