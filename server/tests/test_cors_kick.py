"""Plan X Task 1: CORS regex origins + scheduler interval env floor + upload claim kick (R58)."""

from unittest.mock import AsyncMock

import app.routers.jobs as jobs_router
from app.config import Settings
from tests.conftest import PNG_1PX

async def _preflight(client, origin: str):
    return await client.options(
        "/api/jobs",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )

# ---- CORS (VSCode port-forwarding root cause) ----

async def test_cors_preflight_vscode_dev_allowed(client):
    r = await _preflight(client, "https://abc-5173.vscode.dev")
    assert r.headers.get("access-control-allow-origin") == "https://abc-5173.vscode.dev"

async def test_cors_preflight_localhost_allowed(client):
    r = await _preflight(client, "http://localhost:5173")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

async def test_cors_simple_get_allowed_origin_present(client):
    r = await client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" in r.headers

async def test_cors_evil_origin_absent(client):
    pre = await _preflight(client, "http://evil.example")
    assert "access-control-allow-origin" not in pre.headers
    get = await client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in get.headers

# ---- scheduler_interval_seconds env floor ----

def test_scheduler_interval_env_floor():
    assert Settings(SCHEDULER_INTERVAL_SECONDS=1).scheduler_interval_seconds == 5
    assert Settings().scheduler_interval_seconds == 60

# ---- upload claim kick (R58) ----

async def test_upload_kicks_claim_once(auth_client, monkeypatch):
    mock_run = AsyncMock()
    monkeypatch.setattr(jobs_router.scheduler, "_run_jobs_once", mock_run)
    r = await auth_client.post(
        "/api/jobs", files={"file": ("t.png", PNG_1PX, "image/png")}
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued"
    # ASGITransport awaits background tasks before returning → kick ran after response
    mock_run.assert_awaited_once()

async def test_upload_kick_failure_still_201(auth_client, monkeypatch, caplog):
    mock_run = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(jobs_router.scheduler, "_run_jobs_once", mock_run)
    r = await auth_client.post(
        "/api/jobs", files={"file": ("t.png", PNG_1PX, "image/png")}
    )
    assert r.status_code == 201, r.text
    assert set(r.json()) == {"id", "status", "page_count", "file_type"}
    assert r.json()["status"] == "queued"
    assert mock_run.await_count == 1
    assert any("upload kick failed" in rec.message for rec in caplog.records)
