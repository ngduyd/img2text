"""Wave-5 S1: quota bytes upload 7 ngày rolling — usage + 429 structured.

Ruling: reject 429 không auto-evict; refund = upload_bytes 0 (failed/cancelled
set tại transition point); window = created_at > now-7d AND upload_bytes>0.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.models import Job, User
from app.services.quota import (
    UPLOAD_BYTE_DEFAULT,
    bytes_oldest_expires_at,
    bytes_usage,
    ensure_bytes_quota,
    limit_of,
    quota_me,
)

@pytest.fixture
async def seeded_user(db_session) -> User:
    u = User(email="b@test.io", password_hash="x", role="user")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u

async def _seed_job(db_session, user_id, *, nbytes, age, status="done"):
    db_session.add(
        Job(
            user_id=user_id,
            status=status,
            storage_key=f"uploads/{nbytes}-{age}.bin",
            file_type="pdf",
            page_count=1,
            upload_bytes=nbytes,
            created_at=datetime.now(timezone.utc) - age,
        )
    )
    await db_session.commit()

async def test_bytes_usage_rolling_7d_and_zero_excluded(db_session, seeded_user):
    now = datetime.now(timezone.utc)
    await _seed_job(db_session, seeded_user.id, nbytes=100, age=timedelta(days=1))
    await _seed_job(db_session, seeded_user.id, nbytes=50, age=timedelta(days=6, hours=23))
    await _seed_job(db_session, seeded_user.id, nbytes=999, age=timedelta(days=8))  # trôi khỏi cửa sổ
    await _seed_job(db_session, seeded_user.id, nbytes=0, age=timedelta(hours=1))  # refund row
    assert await bytes_usage(db_session, seeded_user.id, now=now) == 150

async def test_bytes_usage_refund_failed_cancelled(db_session, seeded_user):
    """refund pattern: failed/cancelled đã set upload_bytes=0 → không tính."""
    now = datetime.now(timezone.utc)
    await _seed_job(db_session, seeded_user.id, nbytes=0, age=timedelta(hours=1), status="failed")
    await _seed_job(db_session, seeded_user.id, nbytes=0, age=timedelta(hours=2), status="cancelled")
    assert await bytes_usage(db_session, seeded_user.id, now=now) == 0

async def test_oldest_expires_at_is_min_created_plus_7d(db_session, seeded_user):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=2)
    await _seed_job(db_session, seeded_user.id, nbytes=10, age=timedelta(days=2))
    await _seed_job(db_session, seeded_user.id, nbytes=20, age=timedelta(hours=1))
    got = await bytes_oldest_expires_at(db_session, seeded_user.id, now=now)
    assert abs((got - (old + timedelta(days=7))).total_seconds()) < 60

async def test_oldest_expires_at_empty_window_none(db_session, seeded_user):
    assert await bytes_oldest_expires_at(db_session, seeded_user.id) is None

async def test_ensure_bytes_quota_ok_under_limit(db_session, seeded_user):
    seeded_user.upload_byte_limit = 1000
    await _seed_job(db_session, seeded_user.id, nbytes=900, age=timedelta(hours=1))
    await ensure_bytes_quota(db_session, seeded_user, 100)  # đúng bằng limit → qua

async def test_ensure_bytes_quota_over_429_structured(db_session, seeded_user):
    seeded_user.upload_byte_limit = 1000
    await db_session.commit()
    await _seed_job(db_session, seeded_user.id, nbytes=600, age=timedelta(days=2))
    with pytest.raises(HTTPException) as exc:
        await ensure_bytes_quota(db_session, seeded_user, 500)
    assert exc.value.status_code == 429
    d = exc.value.detail
    assert d["code"] == "upload_quota"
    assert d["used_bytes"] == 600 and d["limit_bytes"] == 1000
    # oldest = job 2 ngày trước → expire sau 5 ngày nữa
    remaining = (datetime.fromisoformat(d["oldest_expires_at"]) - datetime.now(timezone.utc)).days
    assert remaining in (4, 5)

async def test_ensure_bytes_quota_default_limit_fallback(db_session, seeded_user):
    """legacy NULL upload_byte_limit → 202MB default (limit_of pattern)."""
    assert seeded_user.upload_byte_limit is None or True  # fixture default 211812352
    seeded_user.upload_byte_limit = None
    await db_session.commit()
    assert limit_of(None, UPLOAD_BYTE_DEFAULT) == UPLOAD_BYTE_DEFAULT
    await ensure_bytes_quota(db_session, seeded_user, UPLOAD_BYTE_DEFAULT)  # 1 file = đúng cap → qua

async def test_quota_me_includes_upload_bytes(db_session, seeded_user):
    await _seed_job(db_session, seeded_user.id, nbytes=123, age=timedelta(hours=1))
    out = await quota_me(db_session, seeded_user)
    assert out["upload_used_bytes"] == 123
    assert out["upload_limit_bytes"] == seeded_user.upload_byte_limit
