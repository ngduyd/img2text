"""Task 2: core model tests."""

import uuid
from datetime import datetime, timezone

import pytest_asyncio

from app.db import Base, engine
from app.models import RefreshToken, Setting, User


@pytest_asyncio.fixture(autouse=True)
async def _create_tables():
    # ponytail: create_all per test until conftest owns schema bootstrapping.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_create_user_and_refresh(db_session):
    u = User(email="a@b.c", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    t = RefreshToken(
        user_id=u.id,
        jti=uuid.uuid4(),
        token_hash="h",
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(t)
    await db_session.flush()
    assert u.id and t.user_id == u.id
    s = Setting(key="usd_per_gpu_hour", value="0.0")
    db_session.add(s)
    await db_session.flush()
