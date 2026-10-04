"""Background scheduler (Task 8).

ponytail: brief names apscheduler 4.x `AsyncScheduler`; package mirror has no
stable 4.x (only alphas), so this uses stable 3.x `AsyncIOScheduler` with the
same jobs. Upgrade to AsyncScheduler when 4.x is stable on the mirror.
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def init_scheduler(app: FastAPI) -> AsyncIOScheduler:
    """Register jobs; store on app.state.scheduler. Start() skipped under
    pytest (PYTEST_CURRENT_TEST) so tests stay quiet; prod wiring (lifespan)
    starts it unconditionally."""
    scheduler = AsyncIOScheduler()

    async def reap_all() -> None:
        from app.jobs_requeue import reap_leases

        async with app.state.session_factory() as session:
            n = await reap_leases(session)
        logger.info("reap-leases: requeued %d", n)

    scheduler.add_job(
        reap_all, trigger="interval", minutes=1, id="reap-leases"
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
