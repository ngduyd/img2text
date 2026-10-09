"""Phase 1 Task 1-2: DocumentVersion model + doc_versions service."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.models import DocumentVersion, Job, User


async def _job(db_session) -> Job:
    u = User(email="dv@test.io", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    j = Job(user_id=u.id, storage_key="uploads/a.jpg", file_type="image", page_count=1)
    db_session.add(j)
    await db_session.flush()
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
