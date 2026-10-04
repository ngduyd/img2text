"""Shared pytest fixtures for server tests.

Ruling R1: `db_session` (fresh AsyncSession, rollback after each test) and a
function-scoped truncation fixture that clears all tables between tests are
required by Tasks 2+; both are defined here for Task 1.
"""

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, engine
from app.main import create_app


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


@pytest_asyncio.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
