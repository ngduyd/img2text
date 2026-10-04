"""Task 7: request_logs / page_views middleware + prune helpers."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import PageView, RequestLog
from app.middleware import prune_request_logs


async def test_request_logged(client, db_session):
    await client.post("/api/auth/register", json={"email": "m@x.io", "password": "secret123"})
    rows = (await db_session.execute(select(RequestLog))).scalars().all()
    assert any(r.path == "/api/auth/register" and r.status == 201 for r in rows)


async def test_page_view_logged_and_api_excluded(client, db_session):
    await client.get("/")                      # SPA route → 1 page_view
    await client.get("/api/auth/me")           # api → 0 page_views
    pvs = (await db_session.execute(select(PageView))).scalars().all()
    assert sum(1 for p in pvs if p.path == "/") == 1
    assert not any(p.path.startswith("/api") for p in pvs)


async def test_prune_deletes_only_old(db_session):
    db_session.add(RequestLog(method="GET", path="/x", status=200, ip="1.1.1.1",
                              ts=datetime.now(timezone.utc) - timedelta(days=8)))
    db_session.add(RequestLog(method="GET", path="/y", status=200, ip="1.1.1.1"))
    await db_session.flush()
    n = await prune_request_logs(db_session)
    assert n == 1
