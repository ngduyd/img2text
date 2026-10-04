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
    try:
        from app.jobs_requeue import reap_leases  # noqa: F401
    except ImportError:
        # ponytail: jobs_requeue arrives in Plan B; register job once it exists.
        logger.debug("app.jobs_requeue missing; skipping reap-leases job")
    else:
        scheduler.add_job(
            reap_leases, trigger="interval", minutes=1, id="reap-leases"
        )

    async def prune_all() -> None:
        from app.middleware import (
            prune_page_views,
            prune_refresh_tokens,
            prune_request_logs,
        )

        async with app.state.session_factory() as session:
            n_logs = await prune_request_logs(session)
            n_views = await prune_page_views(session)
            n_tokens = await prune_refresh_tokens(session)
        logger.info(
            "daily prune: request_logs=%d page_views=%d refresh_tokens=%d",
            n_logs, n_views, n_tokens,
        )

    scheduler.add_job(prune_all, trigger="cron", hour=3, minute=0, id="daily-prune")
    app.state.scheduler = scheduler
    if "PYTEST_CURRENT_TEST" not in os.environ:
        scheduler.start()
    return scheduler
