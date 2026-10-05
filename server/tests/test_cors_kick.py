"""Plan X Task 1: CORS regex origins + scheduler interval env floor (R58/R58a).
R58a: server-side upload kick deleted (reaper ≠ claim; worker poll ≤30s)."""

from app.config import Settings

async def _preflight(client, origin: str, request_headers: str | None = None):
    headers = {"Origin": origin, "Access-Control-Request-Method": "POST"}
    if request_headers is not None:
        headers["Access-Control-Request-Headers"] = request_headers
    return await client.options("/api/jobs", headers=headers)

# ---- CORS (VSCode port-forwarding root cause) ----

async def test_cors_preflight_vscode_dev_allowed(client):
    r = await _preflight(client, "https://abc-5173.vscode.dev")
    assert r.headers.get("access-control-allow-origin") == "https://abc-5173.vscode.dev"

async def test_cors_preflight_localhost_allowed(client):
    r = await _preflight(client, "http://localhost:5173")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

async def test_cors_preflight_allow_headers_echo(client):
    """R58a: authorization + content-type requested → 200 + allow-headers echo."""
    r = await _preflight(
        client,
        "http://localhost:5173",
        request_headers="authorization,content-type",
    )
    assert r.status_code == 200, r.text
    echoed = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in echoed and "content-type" in echoed

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
