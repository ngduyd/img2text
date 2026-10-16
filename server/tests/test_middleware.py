"""#9 (spec 2026-10-15): email-verify gate trả về 503 khi DB lookup lỗi.

Gate không được passthrough unverified user khi DB down — 503 flat
{code:"service_unavailable"}. Gating bật lại bằng monkeypatch (conftest tắt
bằng env=="test"); MIN_INTERVAL tắt để 3 request liên tiếp không dính 429.
"""

import pytest

from app.core import ratelimit
from app.core.config import settings


@pytest.fixture
def gating_on(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(ratelimit, "MIN_INTERVAL", 0.0)


async def test_email_gate_returns_503_on_db_error(app, client, gating_on, monkeypatch):
    r = await client.post(
        "/api/auth/register", json={"email": "gdb@x.io", "password": "secret123"}
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/auth/login", json={"email": "gdb@x.io", "password": "secret123"}
    )
    assert r.status_code == 200  # access cookie hợp lệ trên client

    async def failing_session_factory(*args, **kwargs):
        raise RuntimeError("db down")

    # DB down SAU khi đã có cookie: gate lookup nổ → 503, không passthrough
    monkeypatch.setattr(app.state, "session_factory", failing_session_factory)
    r = await client.get("/api/jobs")
    assert r.status_code == 503
    assert r.json() == {"code": "service_unavailable"}
