"""Task 2: GET /api/admin/stats aggregates + settings-backed gpu cost."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest_asyncio

from app.models import Job, PageView, Setting, User


def today() -> str:
    """UTC date — pg session TZ is UTC, created_at defaults are UTC."""
    return datetime.now(timezone.utc).date().isoformat()


def d(offset: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


@pytest_asyncio.fixture
async def seeded_stats(db_session):
    """2 users seeded today (+ admin_client bootstrap admin = 3 users today),
    2 done jobs (gpu 3600+7200), 1 failed, 4 page_views today,
    setting usd_per_gpu_hour="2.5"."""
    users = [
        User(email=f"s-{uuid4().hex}@test.io", password_hash="x", role="user")
        for _ in range(2)
    ]
    db_session.add_all(users)
    await db_session.flush()
    for gpu in (3600, 7200):
        db_session.add(
            Job(
                user_id=users[0].id,
                status="done",
                storage_key="k",
                file_type="png",
                page_count=1,
                result={"gpu_seconds": gpu},
            )
        )
    db_session.add(
        Job(
            user_id=users[0].id,
            status="failed",
            storage_key="k",
            file_type="png",
            page_count=0,
        )
    )
    db_session.add_all(PageView(path="/", user_id=users[0].id) for _ in range(4))
    db_session.add(Setting(key="usd_per_gpu_hour", value="2.5"))
    await db_session.commit()
    return db_session


async def test_stats_aggregates(admin_client, seeded_stats):
    r = await admin_client.get(f"/api/admin/stats?from={today()}&to={today()}")
    d0 = r.json()["days"][0]
    assert d0["users_registered"] == 3
    assert d0["jobs_submitted"] == 3 and d0["jobs_done"] == 2 and d0["jobs_failed"] == 1
    assert d0["page_views"] == 4
    assert d0["gpu_seconds"] == 10800.0
    assert d0["estimated_cost_usd"] == 7.5      # 10800/3600 * 2.5


async def test_stats_zero_fill_gap(admin_client):
    r = await admin_client.get(f"/api/admin/stats?from={d(-2)}&to={d(0)}")
    days = r.json()["days"]
    assert len(days) == 3 and days[0]["jobs_submitted"] == 0 and days[0]["users_registered"] == 0


async def test_stats_default_window_7d(admin_client):
    r = await admin_client.get("/api/admin/stats")
    assert len(r.json()["days"]) == 7


async def test_stats_admin_only(auth_client):
    assert (await auth_client.get("/api/admin/stats")).status_code == 403
