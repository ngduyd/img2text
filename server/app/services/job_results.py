"""Result ingestion service (Plan K5 refactor): shared by the worker
POST /result handler (routers/jobs.py) and the Kaggle batch orchestrator.

One conditional UPDATE per path — the ruling R16 pattern: the claim guard
is re-checked AT commit time, closing the read-guard-commit TOCTOU (reaper
requeue + reclaim between guard and write; concurrent double submit).
rowcount 0 = caller maps to 409 / skip; never raises on conflict.

Plan D4: after a successful store the chosen `job.output_format` export is
scheduled fire-and-forget (asyncio.create_task — the /result response and
the batch ingest must not wait on pandoc/LLM). Any generation failure only
logs a warning: the job is already done and ExportBar can export by hand.

Plan proofread: `_schedule_proofread` rides the same task set — OCR done →
LLM proofread best-effort (LLM down → warning, job stays done).
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Job
from app.core.schemas import ResultBody
from app.services.storage import StorageDriver

logger = logging.getLogger(__name__)

# Strong refs: create_task tasks are otherwise GC-eligible while pending.
_pending_output: set[asyncio.Task] = set()

async def _auto_output(job: Job, storage: StorageDriver) -> None:
    try:
        # lazy import: exports → jobs → job_results (cycle if eager)
        from app.routers.exports import auto_generate_output
        await auto_generate_output(job, storage)
    except Exception as exc:
        logger.warning(
            "auto output failed job=%s fmt=%s: %s",
            job.id, job.output_format, exc,
        )

def _schedule_auto_output(job: Job, storage: StorageDriver) -> None:
    task = asyncio.create_task(_auto_output(job, storage))
    _pending_output.add(task)
    task.add_done_callback(_pending_output.discard)

async def _proofread(job: Job) -> None:
    try:
        # own session: request session is closed once the task runs
        from app.core.db import SessionLocal
        from app.services import proofread
        async with SessionLocal() as session:
            await proofread.run_proofread(session, job)
    except Exception as exc:
        # best-effort: proofread failure never affects job status
        logger.warning("proofread failed job=%s: %s", job.id, exc)

def _schedule_proofread(job: Job) -> None:
    """Plan proofread: fire-and-forget after OCR (same task-set pattern)."""
    task = asyncio.create_task(_proofread(job))
    _pending_output.add(task)
    task.add_done_callback(_pending_output.discard)

async def drain_auto_output() -> None:
    """Await every scheduled auto-output + proofread task (tests; shutdown hook later)."""
    while _pending_output:
        await asyncio.gather(*list(_pending_output))

async def _store(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *conds,
    now: datetime,
    storage: StorageDriver | None = None,
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
    # Plan D4: post-commit auto export (SCHEDULED, never blocks the response).
    if storage is not None:
        job = await session.get(Job, job_id)
        if job is not None:
            # identity map may hold the pre-UPDATE instance (expire_on_commit=False)
            await session.refresh(job)
            _schedule_auto_output(job, storage)
            # Plan proofread: song song auto_output — gợi ý sửa lỗi OCR
            # (LLM down → warning bên trong run_proofread, job vẫn done).
            _schedule_proofread(job)
    return True

async def store_worker_result(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *,
    token: str | None,
    now: datetime,
    storage: StorageDriver | None = None,
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
        storage=storage,
    )

async def store_batch_result(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *,
    now: datetime,
    storage: StorageDriver | None = None,
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
        storage=storage,
    )
