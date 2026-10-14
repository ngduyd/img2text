"""Pure-ASGI logging middlewares + retention prune helpers (Task 7).

Ruling R6: pure-ASGI middlewares cannot use Depends — each opens its own
AsyncSession from `app.state.session_factory` (async_sessionmaker set by
create_app). request_logs resolves user_id by decoding the `access` cookie
JWT sub (security.decode_access_sub); any decode failure → user_id=None
(anonymous), never raises. Write failures are logged, never break responses.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import net
from app.core.config import settings
from app.core.deps import ACCESS_COOKIE
from app.core.models import PageView, RefreshToken, RequestLog, User
from app.core.security import decode_access_sub

logger = logging.getLogger(__name__)

_STATIC_SUFFIXES = (".js", ".css", ".png", ".svg", ".ico", ".woff2")


def _normalized_path(scope: Scope) -> str:
    """Path capped at 512 chars. ASGI scope["path"] never carries the query
    string (it lives in scope["query_string"], Ruling R6 brief spec)."""
    return scope["path"][:512]


def _user_id(request: Request) -> int | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    return decode_access_sub(token)


class _LoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _write(self, scope: Scope, status: int) -> None:
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        # Response already sent: a write failure must never break it (Ruling R6).
        try:
            await self._write(scope, status)
        except Exception:
            logger.exception("logging middleware write failed")


class EmailVerifyGateMiddleware:
    """Wave-5 S5: user chưa verify (is_verified=false) → 403 flat
    {code:"email_unverified"} trên MỌI /api/* trừ exempt (auth endpoints
    sinh/refresh verify code + login/logout/refresh — P1-2: user chưa
    verify phải logout/refresh được để resend code). Admin bypass. Không
    có access cookie → không phải user → downstream 401/404 xử lý bình thường.

    Review P2: bỏ entry chết /api/healthz (route thật /healthz không prefix
    → bypass tự nhiên); exempt match strip trailing slash.

    settings.env == "test" → skip (toàn bộ suite cũ không vỡ; test gating
    bật lại bằng monkeypatch). Lookup fail → log + passthrough (downstream
    500/401 — gate không nuốt lỗi DB)."""

    EXEMPT = frozenset(
        {
            "/api/auth/register",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/refresh",
            "/api/auth/verify",
            "/api/auth/verify/resend",
            "/api/auth/password/forgot",
            "/api/auth/password/reset",
        }
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # P2: strip trailing slash trước exempt match
        path = _normalized_path(scope).rstrip("/")
        if (
            not path.startswith("/api/")
            or path in self.EXEMPT
            or settings.env == "test"
        ):
            await self.app(scope, receive, send)
            return
        user_id = _user_id(Request(scope))
        if user_id is not None:
            user = None
            try:
                async with scope["app"].state.session_factory() as session:
                    user = await session.get(User, user_id)
            except Exception:
                logger.exception("email gate: user lookup failed")
            if user is not None and not user.is_verified and user.role != "admin":
                await JSONResponse(
                    status_code=403, content={"code": "email_unverified"}
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)

class RequestLogsMiddleware(_LoggingMiddleware):
    """Writes RequestLog for EVERY request after the response."""

    async def _write(self, scope: Scope, status: int) -> None:
        request = Request(scope)
        log_row = RequestLog(
            method=scope["method"],
            path=_normalized_path(scope),
            status=status,
            user_id=_user_id(request),
            ip=net.client_ip(request),
            # Plan X R60: UA capped at 200 chars; missing header → "" not None
            ua=request.headers.get("user-agent", "")[:200],
        )
        session_factory = scope["app"].state.session_factory
        async with session_factory() as session:
            session.add(log_row)
            await session.commit()


class PageViewsMiddleware(_LoggingMiddleware):
    """Counts GET non-API, non-static-asset requests (SPA page views)."""

    async def _write(self, scope: Scope, status: int) -> None:
        if scope["method"] != "GET":
            return
        path = _normalized_path(scope)
        if path.startswith("/api/") or path.endswith(_STATIC_SUFFIXES):
            return
        pv = PageView(path=path, user_id=_user_id(Request(scope)))
        session_factory = scope["app"].state.session_factory
        async with session_factory() as session:
            session.add(pv)
            await session.commit()


# --- Retention prunes (called by APScheduler in Task 8) ---


async def prune_request_logs(session: AsyncSession, days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await session.execute(delete(RequestLog).where(RequestLog.ts < cutoff))
    return result.rowcount


async def prune_page_views(session: AsyncSession, days: int = 90) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await session.execute(
        delete(PageView).where(PageView.created_at < cutoff)
    )
    return result.rowcount


async def prune_refresh_tokens(session: AsyncSession) -> int:
    """Expired refresh tokens only (expires_at < now)."""
    result = await session.execute(
        delete(RefreshToken).where(
            RefreshToken.expires_at < datetime.now(timezone.utc)
        )
    )
    return result.rowcount
