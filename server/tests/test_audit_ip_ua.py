"""Plan X Task 4: audit rows (RequestLog) capture client IP + User-Agent.

Audit trail = RequestLog rows written by RequestLogsMiddleware for EVERY
request (jobs + auth included); GET /api/admin/logs serves them to admins.
IP trust + XFF handling follows Ruling R5 (rightmost entry, app/net.py) —
leftmost is client-controlled and forgeable.
"""

from sqlalchemy import select

from app.models import RequestLog

async def _health_log(db_session) -> RequestLog:
    rows = (
        await db_session.execute(
            select(RequestLog).where(RequestLog.path == "/healthz")
        )
    ).scalars().all()
    assert rows, "no RequestLog row for /healthz"
    return rows[0]

async def test_audit_captures_ip_and_ua(client, db_session):
    r = await client.get(
        "/healthz",
        headers={
            # leftmost entry client-controlled; nearest proxy appends real client
            "x-forwarded-for": "203.0.113.1, 198.51.100.7",
            "user-agent": "TestUA/1.0",
        },
    )
    assert r.status_code == 200
    row = await _health_log(db_session)
    assert row.ip == "198.51.100.7"
    assert row.ua == "TestUA/1.0"

async def test_audit_captures_ua_capped_200(client, db_session):
    await client.get("/healthz", headers={"user-agent": "U" * 300})
    row = await _health_log(db_session)
    assert row.ua == "U" * 200

async def test_audit_defaults_missing_headers(client, db_session):
    # httpx sends its own UA by default; pop to simulate a header-less request
    client.headers.pop("user-agent", None)
    await client.get("/healthz")
    row = await _health_log(db_session)
    assert row.ip == "127.0.0.1"  # ASGITransport default client host
    assert row.ua == ""

async def test_admin_logs_returns_ip_and_ua(admin_client, db_session):
    r = await admin_client.get(
        "/healthz",
        headers={"x-forwarded-for": "203.0.113.9", "user-agent": "TestUA/2.0"},
    )
    assert r.status_code == 200
    r = await admin_client.get("/api/admin/logs?ip=203.0.113.9")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and items[0]["ip"] == "203.0.113.9"
    assert items[0]["ua"] == "TestUA/2.0"
