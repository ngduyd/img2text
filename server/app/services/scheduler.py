"""Background scheduler (Task 8).

ponytail: brief names apscheduler 4.x `AsyncScheduler`; package mirror has no
stable 4.x (only alphas), so this uses stable 3.x `AsyncIOScheduler` with the
same jobs. Upgrade to AsyncScheduler when 4.x is stable on the mirror.
R58a: server-side upload kick was deleted (reaper ≠ claim); fresh queued
jobs are claimed by workers polling GET /api/jobs/next, the sweep loop only
requeues expired leases.
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from app.core.config import settings
from app.services.kaggle_orchestrator import ensure_worker
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger(__name__)

async def _run_jobs_once() -> None:
    """One claim pass: requeue expired leases (only server-side job advance;
    fresh queued jobs are claimed by workers polling GET /api/jobs/next)."""
    from app.core.db import SessionLocal
    from app.services.jobs_requeue import reap_leases

    async with SessionLocal() as session:
        n = await reap_leases(session)
    logger.info("reap-leases: requeued %d", n)


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
            await _run_jobs_once()
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
    app.state.scheduler = scheduler
    if "PYTEST_CURRENT_TEST" not in os.environ:
        scheduler.start()
    return scheduler
