"""WS-ADMIN quota (spec 2026-10-13): usage windows (ngày local Asia/Ho_Chi_Minh,
tuần T2→CN) + check pre-create. failed/cancelled KHÔNG tính (refund)."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.models import Job, User
from app.services.quota import daily_window, ensure_quota, quota_me, usage, weekly_window


@pytest.fixture
async def seeded_user(db_session) -> User:
    u = User(email="q@test.io", password_hash="x", role="user")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u

async def _seed_job(db_session, user_id, *, pages, status, created_at):
    db_session.add(
        Job(
            user_id=user_id,
            status=status,
            storage_key="uploads/x.pdf",
            file_type="pdf",
            page_count=pages,
            created_at=created_at,
        )
    )
    await db_session.commit()

# --- T3: windows + usage ---

async def test_daily_window_boundary_local_midnight(db_session, seeded_user):
    """00:00 local = 17:00 UTC hôm TRƯỚC — job trước đó thuộc hôm trước."""
    lo, _hi = daily_window()
    await _seed_job(db_session, seeded_user.id, pages=3, status="queued",
                    created_at=lo - timedelta(seconds=1))
    await _seed_job(db_session, seeded_user.id, pages=2, status="done", created_at=lo)
    assert await usage(db_session, seeded_user.id, daily_window()) == 2

async def test_weekly_window_monday_boundary(db_session, seeded_user):
    """Tuần T2→CN: job Chủ nhật local (trước 00:00 T2) không tính tuần này."""
    lo, _hi = weekly_window()
    await _seed_job(db_session, seeded_user.id, pages=7, status="done",
                    created_at=lo - timedelta(seconds=1))
    await _seed_job(db_session, seeded_user.id, pages=4, status="done", created_at=lo)
    assert await usage(db_session, seeded_user.id, weekly_window()) == 4

async def test_failed_cancelled_refund(db_session, seeded_user):
    """Job fail/hủy → hoàn quota (không tính vào usage)."""
    lo, _hi = daily_window()
    for status in ("failed", "cancelled"):
        await _seed_job(db_session, seeded_user.id, pages=5, status=status, created_at=lo)
    assert await usage(db_session, seeded_user.id, daily_window()) == 0

# --- T3: check ---

async def test_ensure_quota_ok_under_limit(db_session, seeded_user):
    await ensure_quota(db_session, seeded_user, 25)  # 0 used → không raise

async def test_ensure_quota_daily_over_429(db_session, seeded_user):
    seeded_user.daily_page_limit = 1
    await db_session.commit()
    lo, _hi = daily_window()
    await _seed_job(db_session, seeded_user.id, pages=1, status="done", created_at=lo)
    with pytest.raises(HTTPException) as exc:
        await ensure_quota(db_session, seeded_user, 1)
    assert exc.value.status_code == 429
    assert exc.value.detail == "Hôm nay bạn đã hết quota (1 trang). Quay lại sau."

async def test_ensure_quota_weekly_over_429(db_session, seeded_user):
    seeded_user.daily_page_limit = 10_000  # chỉ weekly chặn (seed có thể dính cả ngày nếu chạy sớm T2)
    await db_session.commit()
    lo, _hi = weekly_window()
    await _seed_job(db_session, seeded_user.id, pages=150, status="done", created_at=lo)
    with pytest.raises(HTTPException) as exc:
        await ensure_quota(db_session, seeded_user, 1)
    assert exc.value.status_code == 429
    assert exc.value.detail == "Tuần này bạn đã hết quota (150 trang). Quay lại sau."

async def test_quota_me_shape_and_fallback_defaults(db_session, seeded_user):
    """Legacy NULL limits → default 25/150; remaining = max(limit-used, 0)."""
    seeded_user.daily_page_limit = None
    seeded_user.weekly_page_limit = None
    await db_session.commit()
    lo, _hi = daily_window()
    await _seed_job(db_session, seeded_user.id, pages=30, status="done", created_at=lo)
    out = await quota_me(db_session, seeded_user)
    assert out == {
        "daily_limit": 25,
        "daily_used": 30,
        "weekly_limit": 150,
        "weekly_used": 30,
        "daily_remaining": 0,
        "weekly_remaining": 120,
    }
