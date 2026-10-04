"""Task 6: sliding-window rate limit on auth POST endpoints."""


async def test_login_rate_limit_429(client):
    for _ in range(10):
        await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    r = await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    assert r.status_code == 429
    assert r.json() == {"detail": "Quá nhiều yêu cầu."}


async def test_me_not_limited_same_ip(client):
    for _ in range(10):
        await client.post("/api/auth/login", json={"email":"x@y.z","password":"secret123"})
    assert (await client.get("/api/auth/me")).status_code == 401  # limiter only on auth POSTs


async def test_distinct_xff_ips_independent_budgets(client):
    for _ in range(10):
        await client.post(
            "/api/auth/login",
            json={"email": "a@x.io", "password": "secret123"},
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
    r = await client.post("/api/auth/register", json={"email": "a@x.io", "password": "secret123"})
    assert r.status_code == 201
    r = await client.post(
        "/api/auth/login",
        json={"email": "a@x.io", "password": "secret123"},
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    assert r.status_code == 200  # IP B budget independent of IP A
