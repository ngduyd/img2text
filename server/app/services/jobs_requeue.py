"""Plan B: lease reaper — requeue extracting jobs whose lease expired.

Started-at reset is deliberate: a reclaimed job's clock must be honest
(error/result fields untouched). Brief Task 5. spec 2026-10-09: the phase
is "extracting" (both HTTP claim and batch spawn set it; "running" gone).
"""

import logging

from sqlalchemy import func, update

from app.core.models import Job

logger = logging.getLogger(__name__)

async def reap_leases(session) -> int:
    """Requeue expired-lease extracting jobs; returns rows requeued.

    Covers both claim paths: HTTP-claimed (worker_token set) and batch
    (kaggle_ref set); a queued job never carries a lease, untouched.
    """
    result = await session.execute(
        update(Job)
        .where(
            Job.status == "extracting",
            Job.lease_expires_at < func.now(),
        )
        .values(
            status="queued",
            worker_token=None,
            lease_expires_at=None,
            started_at=None,
        )
    )
    await session.commit()
    if result.rowcount:
        logger.info("reap-leases: requeued %d expired lease(s)", result.rowcount)
    return result.rowcount
