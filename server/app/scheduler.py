"""Background scheduler (Task 8).

ponytail: brief names apscheduler 4.x `AsyncScheduler`; package mirror has no
stable 4.x (only alphas), so this uses stable 3.x `AsyncIOScheduler` with the
same jobs. Upgrade to AsyncScheduler when 4.x is stable on the mirror.
"""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import settings

logger = logging.getLogger(__name__)

# R58a: upload kick deleted (reaper ≠ claim); the periodic sweep loop is the
# only claim caller. Lock kept as a cheap guard if a second caller appears.
_claim_lock = asyncio.Lock()

async def _run_jobs_once() -> None:
    """One claim pass: requeue expired leases (only server-side job advance;
    fresh queued jobs are claimed by workers polling GET /api/jobs/next)."""
    from app.db import SessionLocal
    from app.jobs_requeue import reap_leases

    async with SessionLocal() as session:
        n = await reap_leases(session)
    logger.info("reap-leases: requeued %d", n)


def init_scheduler(app: FastAPI) -> AsyncIOScheduler:
    """Register jobs; store on app.state.scheduler. Start() skipped under
    pytest (PYTEST_CURRENT_TEST) so tests stay quiet; prod wiring (lifespan)
    starts it unconditionally."""
    scheduler = AsyncIOScheduler()

    async def reap_all() -> None:
        async with _claim_lock:
            try:
                await _run_jobs_once()
            except Exception:  # one failing pass must not kill the job
                logger.warning("scheduler claim pass failed", exc_info=True)

    scheduler.add_job(
        reap_all,
        trigger="interval",
        seconds=settings.scheduler_interval_seconds,
        id="reap-leases",
    )

    async def prune_all() -> None:
        from app.middleware import (
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
