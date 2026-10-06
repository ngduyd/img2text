"""Plan V (V2): GET /api/jobs/{id}/file/download — same-origin byte stream.

Presigned URLs (STORAGE_PUBLIC_ENDPOINT localhost:4566) unreachable via
VSCode port-forward; server streams original bytes same-origin instead.
Owner-or-admin via jobs._job_or_403.
"""

import pytest_asyncio
from sqlalchemy import select

from app.core.models import Job, User
from tests.conftest import PNG_1PX
from tests.test_jobs_read import other_client  # noqa: F401


@pytest_asyncio.fixture
async def seeded_upload_job(auth_client) -> int:
    """Real upload via auth_client → storage row + job row exist."""
    r = await auth_client.post(
        "/api/jobs", files={"file": ("t.png", PNG_1PX, "image/png")}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest_asyncio.fixture
async def no_storage_row_job(auth_client, db_session) -> int:
    """Job row whose storage_key has no bytes in storage."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="queued",
        storage_key="uploads/does-not-exist.png",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id


@pytest_asyncio.fixture
async def empty_storage_key_job(auth_client, db_session) -> int:
    """Job row with no storage_key at all (pre-upload state)."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="queued",
        storage_key="",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id


async def test_download_owner_200_bytes_content_type_disposition(
    auth_client, seeded_upload_job
):
    r = await auth_client.get(f"/api/jobs/{seeded_upload_job}/file/download")
    assert r.status_code == 200
    assert r.content == PNG_1PX
    assert r.headers["content-type"] == "image/png"
    assert "attachment" in r.headers["content-disposition"]


async def test_download_missing_storage_row_404(auth_client, no_storage_row_job):
    r = await auth_client.get(f"/api/jobs/{no_storage_row_job}/file/download")
    assert r.status_code == 404
    assert r.json()["detail"] == "Không tìm thấy file."


async def test_download_empty_storage_key_404(auth_client, empty_storage_key_job):
    r = await auth_client.get(f"/api/jobs/{empty_storage_key_job}/file/download")
    assert r.status_code == 404
    assert r.json()["detail"] == "Chưa có file."


async def test_download_other_user_403(auth_client, other_client, seeded_upload_job):
    # auth_client FIRST: seeded_upload_job uploads as the first-registered user.
    r = await other_client.get(f"/api/jobs/{seeded_upload_job}/file/download")
    assert r.status_code == 403


async def test_download_admin_200(auth_client, admin_client, seeded_upload_job):
    # auth_client FIRST (job owner); admin_client then overwrites the shared
    # client cookie — admin role passes _job_or_403.
    r = await admin_client.get(f"/api/jobs/{seeded_upload_job}/file/download")
    assert r.status_code == 200
    assert r.content == PNG_1PX
