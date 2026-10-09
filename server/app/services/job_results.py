"""Result ingestion service (Plan K5 refactor): shared by the worker
POST /result handler (routers/jobs.py) and the Kaggle batch orchestrator.

One conditional UPDATE per path — the ruling R16 pattern: the claim guard
is re-checked AT commit time, closing the read-guard-commit TOCTOU (reaper
requeue + reclaim between guard and write; concurrent double submit).
rowcount 0 = caller maps to 409 / skip; never raises on conflict.

Plan D4: after a successful store the chosen `job.output_format` export is
scheduled fire-and-forget (asyncio.create_task — the /result response and
the batch ingest must not wait on pandoc/LLM). spec 2026-10-09: the store
enters phase "rendering"; the completion task flips the job to done
(≥1 layout OK) or failed + failed_step="rendering" (both layouts fail).
Any generation failure only logs a warning.

Plan proofread: `_schedule_proofread` rides the same task set — OCR done →
LLM proofread best-effort (LLM down → warning, job stays done).
"""

import asyncio
import logging
from datetime import datetime, timezone

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
        ok = bool(await auto_generate_output(job, storage))
    except Exception as exc:
        logger.warning(
            "auto output failed job=%s fmt=%s: %s",
            job.id, job.output_format, exc,
        )
        ok = False
    # spec 2026-10-09 completion rule: ≥1 layout OK → done; both fail →
    # failed + failed_step="rendering" (the retry re-runs this step).
    # Own session (the task outlives the request); conditional UPDATE
    # re-checks the phase at commit time — a racing retry task that
    # already flipped the row turns this into a no-op (rowcount 0).
    from app.core.db import SessionLocal  # task-local, as in _proofread
    async with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        values = (
            {"status": "done", "failed_step": None, "finished_at": now}
            if ok
            else {
                "status": "failed",
                "failed_step": "rendering",
                "finished_at": now,
            }
        )
        await session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status.in_(("rendering", "failed")))
            .values(**values)
        )
        await session.commit()

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
                # spec 2026-10-09: ingest stores the result and enters the
                # "rendering" phase; the auto-output task flips to done /
                # failed+failed_step=rendering and stamps finished_at.
                status="rendering",
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
    """Worker protocol: extracting + active lease + token claim → result
    stored (phase "rendering", completion task runs after)."""
    return await _store(
        session,
        job_id,
        body,
        Job.status == "extracting",
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
    """Kaggle batch run finished → result stored ("rendering"). D1 guard
    (K5 review nới): (queued + unclaimed) OR (extracting + unclaimed +
    active lease).

    Batch spawn marks the job extracting (D1), so the old queued-only guard
    would reject the normal path; extracting is accepted only while the spawn
    lease is still valid. queued/extracting jobs never carry a worker_token;
    a worker claim or an expired lease (reaper's turn) flips rowcount to 0
    (caller logs and drops the run)."""
    return await _store(
        session,
        job_id,
        body,
        or_(
            and_(Job.status == "queued", Job.worker_token.is_(None)),
            and_(
                Job.status == "extracting",
                Job.worker_token.is_(None),
                Job.lease_expires_at > now,
            ),
        ),
        now=now,
        storage=storage,
    )
