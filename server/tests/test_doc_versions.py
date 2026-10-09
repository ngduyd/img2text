"""Phase 1 Task 1-2: DocumentVersion model + doc_versions service."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.models import DocumentVersion, Job, User
from app.services.doc_versions import (
    N_VERSIONS,
    latest_version,
    read_version,
    save_version,
    seed_current,
)


async def _job(db_session) -> Job:
    u = User(email="dv@test.io", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    j = Job(user_id=u.id, storage_key="uploads/a.jpg", file_type="image", page_count=1)
    db_session.add(j)
    await db_session.commit()
    return j


async def test_document_version_crud(db_session):
    job = await _job(db_session)
    db_session.add(
        DocumentVersion(
            job_id=job.id, kind="text", storage_key="versions/1/text/1",
            version=1, based_on_text_version=1,
        )
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            select(DocumentVersion).where(DocumentVersion.job_id == job.id)
        )
    ).scalar_one()
    assert row.kind == "text" and row.version == 1
    assert row.detached is False and row.created_at is not None


async def test_document_version_unique_job_kind_version(db_session):
    job = await _job(db_session)
    db_session.add(
        DocumentVersion(job_id=job.id, kind="text", storage_key="k", version=1,
                        based_on_text_version=1)
    )
    await db_session.flush()
    db_session.add(
        DocumentVersion(job_id=job.id, kind="text", storage_key="k2", version=1,
                        based_on_text_version=1)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_jobs_text_version_default(db_session):
    job = await _job(db_session)
    assert job.text_version == 0


# --- Task 2: doc_versions service ---


async def test_save_version_bumps_and_writes_s3(db_session, storage):
    job = await _job(db_session)
    v1 = await save_version(storage, job.id, "text", b"hello", 1)
    v2 = await save_version(storage, job.id, "text", b"hello 2", 2)
    assert (v1.version, v2.version) == (1, 2)
    assert v1.storage_key == f"versions/{job.id}/text/1"
    assert await storage.get(v1.storage_key) == b"hello"
    latest = await latest_version(db_session, job.id, "text")
    assert latest.version == 2
    assert await read_version(storage, v1) == b"hello"


async def test_save_version_prunes_to_n(db_session, storage):
    job = await _job(db_session)
    for i in range(1, N_VERSIONS + 2):
        await save_version(storage, job.id, "md-layout", f"v{i}".encode(), i)
    rows = (
        await db_session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.job_id == job.id)
            .order_by(DocumentVersion.version)
        )
    ).scalars().all()
    assert len(rows) == N_VERSIONS
    assert rows[0].version == 2  # oldest (v1) pruned
    assert not await storage.exists(f"versions/{job.id}/md-layout/1")
    assert await storage.exists(f"versions/{job.id}/md-layout/2")


async def test_latest_version_none_when_empty(db_session, storage):
    job = await _job(db_session)
    assert await latest_version(db_session, job.id, "text") is None


async def test_seed_current_only_first_time(db_session, storage):
    job = await _job(db_session)
    v = await seed_current(storage, job.id, "text", b"seed", 0)
    assert v.version == 1
    again = await seed_current(storage, job.id, "text", b"other", 0)
    assert again.version == 1  # no second seed
    assert await read_version(storage, again) == b"seed"
