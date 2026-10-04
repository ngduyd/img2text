"""Shared pytest fixtures for server tests.

Ruling R1: `db_session` (fresh AsyncSession, rollback after each test) and a
function-scoped truncation fixture that clears all tables between tests are
required by Tasks 2+; both are defined here for Task 1. Session-scoped
`db_schema` owns schema bootstrap: httpx.ASGITransport never runs the app
lifespan (create_all lives in main.lifespan), so a fresh Postgres volume
would otherwise hit UndefinedTable.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import boto3
import httpx
import pytest_asyncio
from moto import mock_aws
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import create_app
from app.models import User
from app.storage import S3Driver


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

@pytest_asyncio.fixture
async def storage_spy(app):
    """Ruling R10: wrap app.state.storage driver methods; real op still runs."""
    driver = app.state.storage
    for name in ("put", "exists", "presign_get", "delete_prefix"):
        setattr(driver, name, AsyncMock(wraps=getattr(driver, name)))
    yield driver
