"""Phase 1 Task 2 (plan 2026-10-10): document version snapshots.

save_version writes bytes to S3 `versions/{job_id}/{kind}/{n}` + inserts a
DocumentVersion row; keeps exactly N_VERSIONS newest per (job, kind) —
older rows AND their S3 objects pruned (prune failure warns, never blocks
the save, per spec error handling).
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import DocumentVersion
from app.services.storage import StorageDriver

logger = logging.getLogger(__name__)

N_VERSIONS = 20
VERSION_KINDS = ("text", "md-layout", "docx-layout")


def version_key(job_id: int, kind: str, version: int) -> str:
    return f"versions/{job_id}/{kind}/{version}"


async def latest_version(
    session: AsyncSession, job_id: int, kind: str
) -> DocumentVersion | None:
    return (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.job_id == job_id, DocumentVersion.kind == kind)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def read_version(storage: StorageDriver, row: DocumentVersion) -> bytes:
    return await storage.get(row.storage_key)


async def save_version(
    storage: StorageDriver,
    job_id: int,
    kind: str,
    data: bytes,
    based_on_text_version: int,
    detached: bool = False,
    session: AsyncSession | None = None,
) -> DocumentVersion:
    """Snapshot bytes + insert row + prune >N. session omitted → SessionLocal.

    version = latest + 1 (UNIQUE(job_id,kind,version) closes the concurrent
    race: the loser's INSERT raises, caller surfaces the error).
    """
    from app.core.db import SessionLocal

    own = session is None
    session = session or SessionLocal()
    try:
        latest = await latest_version(session, job_id, kind)
        version = (latest.version if latest else 0) + 1
        key = version_key(job_id, kind, version)
        await storage.put(key, data)
        row = DocumentVersion(
            job_id=job_id,
            kind=kind,
            storage_key=key,
            version=version,
            based_on_text_version=based_on_text_version,
            detached=detached,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await _prune(storage, session, job_id, kind)
        return row
    finally:
        if own:
            await session.close()


async def _prune(
    storage: StorageDriver, session: AsyncSession, job_id: int, kind: str
) -> None:
    """Keep N_VERSIONS newest; delete older rows + S3 objects (warn on fail)."""
    try:
        keep_from = (
            await latest_version(session, job_id, kind)
        ).version - N_VERSIONS + 1
        stale = (
            await session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.job_id == job_id,
                    DocumentVersion.kind == kind,
                    DocumentVersion.version < keep_from,
                )
            )
        ).scalars().all()
        for row in stale:
            try:
                await storage.delete_prefix(row.storage_key)
            except Exception as exc:
                logger.warning("version S3 prune fail key=%s: %s", row.storage_key, exc)
        await session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.job_id == job_id,
                DocumentVersion.kind == kind,
                DocumentVersion.version < keep_from,
            )
        )
        await session.commit()
    except Exception as exc:
        logger.warning("version prune fail job=%s kind=%s: %s", job_id, kind, exc)


async def seed_current(
    storage: StorageDriver,
    job_id: int,
    kind: str,
    data: bytes,
    based_on_text_version: int,
    session: AsyncSession | None = None,
) -> DocumentVersion | None:
    """Lazy-seed: current artifact becomes version 1 on first access.

    No-op (returns the existing latest row) when any version exists —
    existing jobs predate document_versions (Review Focus: first version).
    """
    from app.core.db import SessionLocal

    own = session is None
    session = session or SessionLocal()
    try:
        existing = await latest_version(session, job_id, kind)
        if existing is not None:
            return existing
        return await save_version(
            storage, job_id, kind, data, based_on_text_version, session=session
        )
    finally:
        if own:
            await session.close()
