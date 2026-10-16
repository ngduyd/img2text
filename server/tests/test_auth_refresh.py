"""Task 4: refresh rotation, reuse detection, logout."""

async def _register_login(client):
    await client.post("/api/auth/register", json={"email":"r@x.io","password":"secret123"})
    await client.post("/api/auth/login", json={"email":"r@x.io","password":"secret123"})

async def test_refresh_rotates(client):
    await _register_login(client)
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200 and "refresh" in r.cookies

async def test_refresh_reuse_revokes_family(client):
    await _register_login(client)
    stolen = client.cookies.get("refresh")
    r1 = await client.post("/api/auth/refresh")        # rotate: stolen now used
    assert r1.status_code == 200
    fresh = r1.cookies.get("refresh")                  # F from response Set-Cookie
    assert fresh
    client.cookies.set("refresh", stolen)              # replay OLD rotated-out token
    assert (await client.post("/api/auth/refresh")).status_code == 401  # replay detected
    client.cookies.set("refresh", fresh)               # F, but family revoked above
    assert (await client.post("/api/auth/refresh")).status_code == 401  # family revocation

async def test_logout_revokes(client):
    await _register_login(client)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 401

async def test_revoke_sessions_deletes_refresh_tokens(client):
    """P2 #17: POST /api/auth/session/revoke xoá toàn bộ refresh token (204)."""
    await _register_login(client)
    assert (await client.post("/api/auth/refresh")).status_code == 200  # có refresh hợp lệ
    assert (await client.post("/api/auth/session/revoke")).status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401  # đã bị revoke
