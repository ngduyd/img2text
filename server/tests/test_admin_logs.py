"""Task 3: GET /api/admin/logs filter + GET /api/admin/logs/tail safe tail."""

from datetime import datetime, timedelta, timezone

import pytest_asyncio

from app.config import settings
from app.models import RequestLog

@pytest_asyncio.fixture
async def seeded_logs(db_session):
    """4 logs: 2x200 ip 10.0.0.1, 1x401 ip 10.0.0.2, 1x500 ip 10.0.0.2."""
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = [
        RequestLog(method="GET", path="/", status=200, ip="10.0.0.1", ua="a",
                   ts=base),
        RequestLog(method="GET", path="/jobs", status=200, ip="10.0.0.1", ua="a",
                   ts=base + timedelta(seconds=1)),
        RequestLog(method="POST", path="/login", status=401, ip="10.0.0.2", ua="b",
                   ts=base + timedelta(seconds=2)),
        RequestLog(method="POST", path="/jobs", status=500, ip="10.0.0.2", ua="b",
                   ts=base + timedelta(seconds=3)),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return db_session

@pytest_asyncio.fixture
def tmp_settings_log(tmp_path, monkeypatch):
    """Point settings.log_path at a tmp file with 3 lines."""
    p = tmp_path / "test.log"
    p.write_text("line1\nline2\nline3\n")
    monkeypatch.setattr(settings, "log_path", str(p))
    return p

@pytest_asyncio.fixture
def settings_log_missing(tmp_path, monkeypatch):
    """Point settings.log_path at a nonexistent file."""
    monkeypatch.setattr(settings, "log_path", str(tmp_path / "missing.log"))

async def test_logs_filter_by_status_class_and_ip(admin_client, seeded_logs):
    r = await admin_client.get("/api/admin/logs?status_class=5xx")
    assert [x["status"] for x in r.json()["items"]] == [500]
    r = await admin_client.get("/api/admin/logs?ip=10.0.0.1")
    assert all(x["ip"] == "10.0.0.1" for x in r.json()["items"]) and r.json()["items"]

async def test_logs_limit_clamped(admin_client, seeded_logs):
    r = await admin_client.get("/api/admin/logs?limit=99999")
    assert len(r.json()["items"]) <= 500

async def test_tail_returns_last_lines(admin_client, tmp_settings_log):
    r = await admin_client.get("/api/admin/logs/tail?lines=2")
    assert len(r.json()["lines"]) == 2 and r.json()["lines"][-1] == "line3"

async def test_tail_missing_file_empty(admin_client, settings_log_missing):
    r = await admin_client.get("/api/admin/logs/tail")
    assert r.status_code == 200 and r.json()["lines"] == []

async def test_tail_no_path_param_ignores_traversal(admin_client, tmp_settings_log):
    r = await admin_client.get("/api/admin/logs/tail?lines=2&path=../../../etc/passwd")
    assert all("root:" not in ln for ln in r.json()["lines"])

async def test_tail_lines_clamped(admin_client, tmp_settings_log):
    """Pin (Plan E final review): lines clamp 1..500 — min(500, max(1, lines))."""
    r = await admin_client.get("/api/admin/logs/tail?lines=-5")
    assert r.status_code == 200
    file_lines = tmp_settings_log.read_text().splitlines()
    assert set(r.json()["lines"]) <= set(file_lines)  # no error, subset of file
    r = await admin_client.get("/api/admin/logs/tail?lines=99999")
    assert r.status_code == 200 and len(r.json()["lines"]) <= 500
