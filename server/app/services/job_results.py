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
from app.core.security import hash_worker_token
from app.services.storage import StorageDriver

logger = logging.getLogger(__name__)

# Strong refs: create_task tasks are otherwise GC-eligible while pending.
_pending_output: set[asyncio.Task] = set()
# P1: job_id → live auto-output task. Single-flight guard (one task per job
# on the single loop) + the stale-rendering sweep's in-process registry.
_active_outputs: dict[int, asyncio.Task] = {}

async def _auto_output(job: Job, storage: StorageDriver) -> None:
    # WS-SERVER queue: render ≤ 2 pass. Claim (clear) cờ TRƯỚC mỗi pass —
    # pass đầu tiên đã là lần "vẽ lại" cho cờ có sẵn; cờ mới bật DURING
    # render (user save giữa chừng) → thêm 1 pass nữa. Guard 2: quá 2 pass
    # → done + GIỮ cờ + log warning (sweep nhắc lại sau).
    from app.core.db import SessionLocal  # task-local, as in _proofread
    renders = 0
    while True:
        renders += 1
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job.id, Job.rerender_requested.is_(True))
                .values(rerender_requested=False)
            )
            await session.commit()
            # P1-1: mỗi pass render bằng row MỚI — user save GIỮA 2 pass đổi
            # result/rerender_requested/mode; object truyền vào task là stale.
            fresh = await session.get(Job, job.id)
        if fresh is not None:
            job = fresh  # session đóng → detached, attributes đã load
        try:
            # Phase 5: extract_only — no layout requested; OCR result alone
            # completes the job (no artifacts, no rendering phase failure).
            if job.mode == "extract_only":
                ok = True
            else:
                # lazy import: exports → jobs → job_results (cycle if eager)
                from app.routers.exports import auto_generate_output
                ok = bool(await auto_generate_output(job, storage))
        except Exception as exc:
            logger.warning(
                "auto output failed job=%s fmt=%s: %s",
                job.id, job.output_format, exc,
            )
            ok = False
        async with SessionLocal() as session:
            fresh = await session.get(Job, job.id)
            flag_set = bool(fresh is not None and fresh.rerender_requested)
        if not flag_set:
            break
        if renders >= 2:
            logger.warning(
                "rerender guard: job %s quá %d lần render — giữ cờ "
                "rerender_requested, không vẽ lại lần nữa",
                job.id, renders,
            )
            break
        logger.info(
            "rerender queued job=%s — vẽ lại layout (pass %d)",
            job.id, renders + 1,
        )
    # spec 2026-10-09 completion rule: ≥1 layout OK → done; both fail →
    # failed + failed_step="rendering" (the retry re-runs this step).
    # Own session (the task outlives the request); conditional UPDATE
    # re-checks the phase at commit time — a racing retry task that
    # already flipped the row turns this into a no-op (rowcount 0).
    async with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        values = (
            {"status": "done", "failed_step": None, "finished_at": now}
            if ok
            else {
                "status": "failed",
                "failed_step": "rendering",
                "finished_at": now,
                # wave-5 S1 refund: failed → hoàn bytes
                "upload_bytes": 0,
            }
        )
        await session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status.in_(("rendering", "failed")))
            .values(**values)
        )
        await session.commit()

def _schedule_auto_output(job: Job, storage: StorageDriver) -> None:
    running = _active_outputs.get(job.id)
    if running is not None and not running.done():
        logger.warning("auto output job=%s already running — skip", job.id)
        return
    task = asyncio.create_task(_auto_output(job, storage))
    _pending_output.add(task)
    _active_outputs[job.id] = task

    def _forget(t: asyncio.Task, job_id: int = job.id) -> None:
        _pending_output.discard(t)
        if _active_outputs.get(job_id) is t:
            del _active_outputs[job_id]

    task.add_done_callback(_forget)

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

def _dump_result(body: ResultBody) -> dict:
    """model_dump + bỏ key html/cells khi None (region không bảng giữ nguyên
    shape cũ — wave-3 review P2: model_dump() rải None keys vào mọi region)."""
    d = body.model_dump()
    for pg in d.get("pages") or []:
        for r in pg.get("regions") or []:
            for k in ("html", "cells"):
                if r.get(k) is None:
                    r.pop(k, None)
    return d

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
                # wave-3: non-table region KHÔNG mang key html/cells=None
                # (shape cũ không đổi; bbox=None vẫn giữ key nullable).
                result=_dump_result(body),
                # spec 2026-10-09: ingest stores the result and enters the
                # "rendering" phase; the auto-output task flips to done /
                # failed+failed_step=rendering and stamps finished_at.
                status="rendering",
                # #6 quota retro-correct: page_count = SỐ TRANG THẬT từ OCR
                # result (batch + loop cùng qua đây) — SUM quota phản ánh
                # ngay job đầu, chống khai láo khi create.
                page_count=len(body.pages),
                worker_token_hash=None,
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
        # P2 #16: hash-at-rest — so khớp sha256(token) với hash đã lưu
        # (gate /result validate token trước khi vào đây)
        Job.worker_token_hash == hash_worker_token(token),
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
    lease is still valid. queued/extracting jobs never carry a worker_token_hash;
    a worker claim or an expired lease (reaper's turn) flips rowcount to 0
    (caller logs and drops the run)."""
    return await _store(
        session,
        job_id,
        body,
        or_(
            and_(
                Job.status == "queued",
                Job.worker_token_hash.is_(None),
                # spec session worker T4: batch không clobber session claim
                Job.session_id.is_(None),
            ),
            and_(
                Job.status == "extracting",
                Job.worker_token_hash.is_(None),
                Job.session_id.is_(None),
                Job.lease_expires_at > now,
            ),
        ),
        now=now,
        storage=storage,
    )

async def store_session_result(
    session: AsyncSession,
    job_id: int,
    body: ResultBody,
    *,
    session_id: int,
    now: datetime,
    storage: StorageDriver | None = None,
) -> bool:
    """Kaggle session worker (spec 2026-10-16 T4): result stored
    ("rendering") với session-scope claim re-check — atomic (R16): one
    conditional UPDATE WHERE extracting + lease active + session_id khớp
    (khác session / lease hết → rowcount 0 → caller 409/no-op)."""
    return await _store(
        session,
        job_id,
        body,
        Job.status == "extracting",
        Job.lease_expires_at > now,
        Job.session_id == session_id,
        now=now,
        storage=storage,
    )
