"""Lane C1 (spec R): 1s/1req per (client IP, UA hash) trên auth + feedback.

settings.env == "test" (conftest) → limiter bypass; test bật lại bằng
monkeypatch (pattern EmailVerifyGateMiddleware).
"""

import time

import pytest

from app.core import ratelimit
from app.core.config import settings
from app.core.ratelimit import SlidingInterval

LOGIN = {"email": "a@x.io", "password": "badpass1"}


@pytest.fixture
def limiter_on(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")


async def test_second_hit_429(client, limiter_on):
    kw = {"json": LOGIN, "headers": {"user-agent": "UA-1"}}
    assert (await client.post("/api/auth/login", **kw)).status_code == 401
    r2 = await client.post("/api/auth/login", **kw)
    assert r2.status_code == 429
    assert r2.json() == {"code": "rate_limited"}


async def test_different_ua_allowed(client, limiter_on):
    base = {"json": LOGIN}
    assert (
        await client.post(
            "/api/auth/login", **base, headers={"user-agent": "UA-1"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/auth/login", **base, headers={"user-agent": "UA-2"}
        )
    ).status_code == 401


async def test_feedback_post_limited(client, limiter_on):
    kw = {"json": {"content": "hi"}, "headers": {"user-agent": "UA-1"}}
    assert (await client.post("/api/feedback", **kw)).status_code == 401
    r2 = await client.post("/api/feedback", **kw)
    assert r2.status_code == 429
    assert r2.json() == {"code": "rate_limited"}


async def test_bypass_when_env_test(client):
    # conftest sets settings.env == "test" → limiter skip
    kw = {"json": LOGIN, "headers": {"user-agent": "UA-1"}}
    assert (await client.post("/api/auth/login", **kw)).status_code == 401
    assert (await client.post("/api/auth/login", **kw)).status_code == 401


def test_prune_old_entries():
    lim = SlidingInterval()
    assert lim.allow("k")
    lim._last["stale"] = time.monotonic() - 120  # older than PRUNE_AGE
    assert lim.allow("other")
    assert "stale" not in lim._last


def test_bounded_max_keys(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 3)
    lim = SlidingInterval()
    for i in range(6):
        assert lim.allow(f"k{i}")
    assert len(lim._last) <= 3
