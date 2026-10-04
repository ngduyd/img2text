"""Plan B: lease reaper — requeue running jobs whose lease expired.

Started-at reset is deliberate: a reclaimed job's clock must be honest
(error/result fields untouched). Brief Task 5.
"""

import logging

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job

logger = logging.getLogger(__name__)

async def reap_leases(session) -> int:
    """Requeue expired-lease running jobs; returns rows requeued."""
    result = await session.execute(
        update(Job)
        .where(
            Job.status == "running",
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
