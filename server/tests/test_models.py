"""Task 2: core model tests."""

import uuid
from datetime import datetime, timezone

from app.models import Job, RefreshToken, Setting, User


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
    j = Job(
        user_id=u.id,
        storage_key="uploads/abc.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(j)
    await db_session.flush()
    assert j.id and j.user_id == u.id and j.status == "queued"
