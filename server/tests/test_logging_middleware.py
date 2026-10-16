"""Task 7: request_logs / page_views middleware + prune helpers."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.models import PageView, RequestLog
from app.core.middleware import prune_request_logs


async def test_request_logged(client, app, db_session):
    await client.post("/api/auth/register", json={"email": "m@x.io", "password": "secret123"})
    from app.core.middleware import flush_request_logs
    await flush_request_logs(app)  # P2 #18: buffer → DB trước khi assert
    rows = (await db_session.execute(select(RequestLog))).scalars().all()
    assert any(r.path == "/api/auth/register" and r.status == 201 for r in rows)


async def test_request_log_resolves_authenticated_user(client, app, db_session):
    email, password = "auth@x.io", "secret123"
    r = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    user_id = r.json()["id"]
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    from app.core.middleware import flush_request_logs
    await flush_request_logs(app)  # P2 #18: buffer → DB trước khi assert
    rows = (await db_session.execute(
        select(RequestLog).where(RequestLog.path == "/api/auth/me")
    )).scalars().all()
    assert rows, "no RequestLog row for /api/auth/me"
    assert rows[0].user_id is not None
    assert rows[0].user_id == user_id

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

async def test_request_logs_buffered_not_written_immediately(client, db_session):
    """P2 #18: row nằm in-memory buffer, CHƯA ghi DB cho tới khi flush."""
    from sqlalchemy import func

    initial = await db_session.scalar(select(func.count()).select_from(RequestLog))
    await client.get("/healthz")
    after = await db_session.scalar(select(func.count()).select_from(RequestLog))
    assert after == initial  # vẫn buffered

async def test_flush_job_writes_buffered_logs(client, app, db_session):
    """P2 #18: flush_request_logs (scheduler job, 30s) bulk-insert buffer."""
    from sqlalchemy import func

    await client.get("/healthz")
    await client.get("/healthz")
    from app.core.middleware import flush_request_logs

    assert await flush_request_logs(app) >= 2
    n = await db_session.scalar(select(func.count()).select_from(RequestLog))
    assert n >= 2
