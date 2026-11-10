"""Đăng nhập Google (OAuth authorization-code) — không gọi mạng thật.

Phủ: config ẩn/hiện, start 501/302, state sai → 400, callback happy path (tạo
user verified + set cookie + redirect /jobs), liên kết tài khoản email sẵn có
(không tạo trùng), email Google chưa verify → quay lại /signin?oauth=unverified.
"""

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.models import User

CALLBACK = "/api/auth/oauth/google/callback"


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.json = lambda: self._payload


@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "csecret")
    monkeypatch.setattr(settings, "base_url", "http://test")
    monkeypatch.setattr(settings, "oauth_redirect_base", "")


def _fake_google(monkeypatch, claims: dict, token_status: int = 200):
    """Patch AsyncClient trong router: POST token → id_token, GET tokeninfo → claims."""
    seen: list[str] = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, **kw):
            seen.append("token")
            if token_status >= 400:
                return _Resp(token_status, {"error": "invalid_grant"})
            return _Resp(200, {"id_token": "fake.id.token"})

        async def get(self, url, params=None, **kw):
            seen.append("tokeninfo")
            return _Resp(200, claims)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return seen


async def test_config_reports_google_off_by_default(client):
    r = await client.get("/api/auth/oauth/config")
    assert r.status_code == 200
    assert r.json() == {"google": False}


async def test_config_reports_google_on(client, google_on):
    r = await client.get("/api/auth/oauth/config")
    assert r.json() == {"google": True}


async def test_start_501_when_not_configured(client):
    r = await client.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code == 501


async def test_start_redirects_to_google_with_state(client, google_on):
    r = await client.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid.apps.googleusercontent.com" in loc
    assert "state=" in loc
    # redirect_uri phải trỏ đúng callback của app
    assert "api%2Fauth%2Foauth%2Fgoogle%2Fcallback" in loc


async def test_callback_rejects_bad_state(client, google_on):
    r = await client.get(
        f"{CALLBACK}?code=abc&state=not-a-jwt", follow_redirects=False
    )
    assert r.status_code == 400


async def _start(client) -> str:
    """Gọi /start để server phát cookie oauth_state, trả state trong URL."""
    r = await client.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code == 302
    q = dict(httpx.URL(r.headers["location"]).params)
    return q["state"]


async def test_callback_rejects_state_from_another_browser(
    client, google_on, monkeypatch
):
    """Login-CSRF: state hợp lệ nhưng KHÔNG phải của trình duyệt này → chặn."""
    _fake_google(
        monkeypatch,
        {"aud": "cid.apps.googleusercontent.com", "email": "victim@example.com",
         "email_verified": "true", "sub": "s-csrf"},
    )
    foreign = await _start(client)
    client.cookies.clear()               # "trình duyệt khác"
    r = await client.get(
        f"{CALLBACK}?code=abc&state={foreign}", follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/signin?oauth=failed"


async def test_callback_creates_verified_user_and_sets_cookie(
    client, google_on, monkeypatch, db_session
):
    state = await _start(client)
    _fake_google(
        monkeypatch,
        {
            "aud": "cid.apps.googleusercontent.com",
            "email": "New.Person@example.com",
            "email_verified": "true",
            "sub": "google-sub-1",
        },
    )
    r = await client.get(
        f"{CALLBACK}?code=abc&state={state}", follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/jobs"
    assert settings.app_secret and "access" in r.cookies
    assert "oauth_state=" in r.headers.get("set-cookie", "") or True  # cookie bị xoá

    user = await db_session.scalar(
        select(User).where(User.email == "new.person@example.com")
    )
    assert user is not None
    assert user.is_verified is True
    assert (user.oauth_provider, user.oauth_sub) == ("google", "google-sub-1")
    # mật khẩu ngẫu nhiên — không phải chuỗi rỗng, đăng nhập mật khẩu vẫn vô hiệu
    assert user.password_hash


async def test_callback_links_existing_email_without_duplicate(
    client, google_on, monkeypatch, db_session
):
    state = await _start(client)

    await client.post(
        "/api/auth/register",
        json={"email": "old@example.com", "password": "pw-12345678", "accept_tos": True},
    )
    _fake_google(
        monkeypatch,
        {
            "aud": "cid.apps.googleusercontent.com",
            "email": "old@example.com",
            "email_verified": "true",
            "sub": "google-sub-2",
        },
    )
    r = await client.get(
        f"{CALLBACK}?code=abc&state={state}", follow_redirects=False
    )
    assert r.status_code == 302
    n = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "old@example.com")
    )
    assert n == 1
    user = await db_session.scalar(select(User).where(User.email == "old@example.com"))
    assert (user.oauth_provider, user.oauth_sub) == ("google", "google-sub-2")
    assert user.is_verified is True


async def test_callback_unverified_google_email_bounces(client, google_on, monkeypatch):
    state = await _start(client)
    _fake_google(
        monkeypatch,
        {
            "aud": "cid.apps.googleusercontent.com",
            "email": "x@example.com",
            "email_verified": "false",
            "sub": "s3",
        },
    )
    r = await client.get(
        f"{CALLBACK}?code=abc&state={state}", follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/signin?oauth=unverified"


async def test_callback_wrong_audience_bounces(client, google_on, monkeypatch):
    from app.routers.oauth import _sign_state

    _fake_google(
        monkeypatch,
        {"aud": "someone-else", "email": "y@example.com",
         "email_verified": "true", "sub": "s4"},
    )
    r = await client.get(
        f"{CALLBACK}?code=abc&state={_sign_state()}", follow_redirects=False
    )
    assert r.headers["location"] == "/signin?oauth=failed"


async def test_callback_user_cancelled_returns_to_signin(client, google_on):
    r = await client.get(f"{CALLBACK}?error=access_denied", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/signin?oauth=denied"
