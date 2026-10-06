"""Result ingestion service (Plan K5 refactor): shared by the worker
POST /result handler (routers/jobs.py) and the Kaggle batch orchestrator.

One conditional UPDATE per path — the ruling R16 pattern: the claim guard
is re-checked AT commit time, closing the read-guard-commit TOCTOU (reaper
requeue + reclaim between guard and write; concurrent double submit).
rowcount 0 = caller maps to 409 / skip; never raises on conflict.
"""

from datetime import datetime

from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Job
from app.core.schemas import ResultBody

async def _store(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *conds,
    now: datetime,
) -> bool:
    rowcount = (
        await session.execute(
            update(Job)
            .where(Job.id == job_id, *conds)
            .values(
                result=body.model_dump(),
                status="done",
                finished_at=now,
                worker_token=None,
                lease_expires_at=None,
            )
        )
    ).rowcount
    if rowcount == 0:
        return False
    await session.commit()
    return True

async def store_worker_result(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *,
    token: str | None,
    now: datetime,
) -> bool:
    """Worker protocol: running + active lease + token claim → done."""
    return await _store(
        session,
        job_id,
        body,
        Job.status == "running",
        Job.lease_expires_at > now,
        Job.worker_token == token,
        now=now,
    )

async def store_batch_result(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *,
    now: datetime,
) -> bool:
    """Kaggle batch run finished → done. D1 guard (K5 review nới):
    (queued + unclaimed) OR (running + unclaimed + active lease).

    Batch spawn marks the job running (D1), so the old queued-only guard
    would reject the normal path; running is accepted only while the spawn
    lease is still valid. queued/running jobs never carry a worker_token;
    a worker claim or an expired lease (reaper's turn) flips rowcount to 0
    (caller logs and drops the run)."""
    return await _store(
        session,
        job_id,
        body,
        or_(
            and_(Job.status == "queued", Job.worker_token.is_(None)),
            and_(
                Job.status == "running",
                Job.worker_token.is_(None),
                Job.lease_expires_at > now,
            ),
        ),
        now=now,
    )
