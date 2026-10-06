"""Shared pytest fixtures for server tests.

Ruling R1: `db_session` (fresh AsyncSession, rollback after each test) and a
function-scoped truncation fixture that clears all tables between tests are
required by Tasks 2+; both are defined here for Task 1. Session-scoped
`db_schema` owns schema bootstrap: httpx.ASGITransport never runs the app
lifespan (create_all lives in main.lifespan), so a fresh Postgres volume
would otherwise hit UndefinedTable.
"""

import base64
import os
import tempfile
from unittest.mock import AsyncMock
from uuid import uuid4

# weasyprint first-run font-cache warning must not pollute pytest output;
# point its cache at a tempdir (v70 removed the cache dir, kept for safety)
os.environ.setdefault("WEASYPRINT_CACHE_DIR", tempfile.gettempdir())

import boto3
import httpx
import pytest_asyncio
from moto import mock_aws
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_bootstrap import bootstrap_admin
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.main import create_app
from app.core.models import Job, User
from app.services.storage import S3Driver


@pytest_asyncio.fixture(scope="session", autouse=True)
async def db_schema():
    """Session-scoped: create schema ONCE against the test engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Fresh AsyncSession per test; rollback after each test."""
    session = SessionLocal()
    yield session
    await session.rollback()
    await session.close()


@pytest_asyncio.fixture(autouse=True)
async def db_truncate():
    """Function-scoped: truncate all tables between tests."""
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public'"
                )
            )
        ).scalars().all()
        if tables:
            await conn.execute(
                text(
                    "TRUNCATE "
                    + ", ".join(tables)
                    + " RESTART IDENTITY CASCADE"
                )
            )
    yield


async def grant_ocr(session: AsyncSession, email: str) -> None:
    """Ruling R10: enable ocr_enabled directly in DB (no admin HTTP flow)."""
    await session.execute(
        update(User).where(User.email == email).values(ocr_enabled=True)
    )
    await session.commit()

@pytest_asyncio.fixture
async def app():
    """create_app() with moto-backed S3 driver wired into app.state.storage."""
    application = create_app()
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="img2text-test"
        )
        application.state.storage = S3Driver(
            endpoint=None,
            key_id="test-key",
            secret="test-secret",
            bucket="img2text-test",
            region="us-east-1",
        )
        yield application

@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def auth_client(client, db_session):
    """Ruling R10: fresh registered+logged-in user, ocr_enabled granted."""
    email = f"u-{uuid4().hex}@test.io"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201, r.text
    await grant_ocr(db_session, email)
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 200, r.text
    return client

@pytest_asyncio.fixture
async def admin_client(client, db_session):
    """Ruling R28: per-test bootstrap admin (AFTER truncate) + cookies.

    Register may 409 (bootstrap already created the email); login is what
    sets the access cookie.
    """
    await bootstrap_admin(db_session, "admin@test.local", "adminpass1")
    r = await client.post(
        "/api/auth/register",
        json={"email": "admin@test.local", "password": "adminpass1"},
    )
    assert r.status_code in (201, 409), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": "admin@test.local", "password": "adminpass1"},
    )
    assert r.status_code == 200, r.text
    return client

@pytest_asyncio.fixture
async def worker_client(app, monkeypatch):
    """Ruling R10: bearer-authenticated client; test runner_key value."""
    monkeypatch.setattr(settings, "runner_key", "test-runner-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-runner-key"},
    ) as c:
        yield c

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

@pytest_asyncio.fixture
async def worker_client2(app, monkeypatch):
    """Second Bearer client, same runner key (concurrency tests)."""
    monkeypatch.setattr(settings, "runner_key", "test-runner-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-runner-key"},
    ) as c:
        yield c

@pytest_asyncio.fixture
async def client_no_runner_key(app):
    """Plain client without Authorization header (runner-key 401 tests)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def seed_job(auth_client) -> int:
    """Real uploaded job (status queued); returns job id."""
    r = await auth_client.post(
        "/api/jobs", files={"file": ("t.png", PNG_1PX, "image/png")}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]

@pytest_asyncio.fixture
def VALID_RESULT_JSONB() -> dict:
    """Spec §4 result shape: 1 page, verdicts ok + image_unextractable."""
    return {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 12.5,
        "warnings": [],
        "markdown": "# tài liệu\n\n## Phần 2",
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "page_flag": "ok",
                "markdown": "# tài liệu\n\n## Phần 2",
                "regions": [
                    {
                        "id": "r0",
                        "bbox": [1, 2, 30, 40],
                        "text": "Xin chào",
                        "verdict": "ok",
                        "placeholder": False,
                    },
                    {
                        "id": "r1",
                        "bbox": [5, 6, 70, 80],
                        "text": "",
                        "verdict": "image_unextractable",
                        "placeholder": True,
                    },
                ],
            }
        ],
    }

@pytest_asyncio.fixture
async def done_job_with_result(auth_client, db_session, VALID_RESULT_JSONB) -> int:
    """Ruling R24: done job owned by the auth_client user (uploaded state
    faked directly); returns job id."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=VALID_RESULT_JSONB,
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

@pytest_asyncio.fixture
async def storage(app):
    """Raw app.state.storage driver (no spies)."""
    return app.state.storage

@pytest_asyncio.fixture
async def storage_spy(app):
    """Ruling R10: wrap app.state.storage driver methods; real op still runs."""
    driver = app.state.storage
    for name in ("put", "exists", "presign_get", "delete_prefix", "get"):
        setattr(driver, name, AsyncMock(wraps=getattr(driver, name)))
    yield driver
