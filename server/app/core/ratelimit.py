"""In-memory 1s/1req sliding limiter for auth + feedback endpoints (Lane C1, spec R).

key = (client IP, User-Agent hash) → min interval 1s; violation → 429
{code:"rate_limited"}. Skip khi settings.env=="test" (pattern
EmailVerifyGateMiddleware — toàn bộ suite cũ không vỡ).

ponytail: single-process dict, restart resets — upgrade Redis khi
multi-instance.
"""

import hashlib
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import net
from app.core.config import settings

MIN_INTERVAL = 1.0   # seconds between two allowed hits per key
PRUNE_AGE = 60.0     # last-seen older than this → dead weight, drop
MAX_KEYS = 10_000    # bounded dict: over cap → evict oldest first

# Spec R: auth endpoints + POST /api/feedback. Exact match (rstrip "/")
# — /api/auth/profile (profile router, same prefix) KHÔNG thuộc set.
PROTECTED = frozenset(
    {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/verify",
        "/api/auth/verify/resend",
        "/api/auth/password/forgot",
        "/api/auth/password/reset",
        "/api/feedback",
    }
)

class SlidingInterval:
    """key → last-seen monotonic ts. Hit within MIN_INTERVAL → deny; the
    denied hit does NOT refresh ts (không starvation: sau 1s từ lần đầu
    là allowed lại)."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(now)
        last = self._last.get(key)
        if last is not None and now - last < MIN_INTERVAL:
            return False
        self._last[key] = now
        self._bound()
        return True

    def _prune(self, now: float) -> None:
        # Age prune: entry cũ hơn PRUNE_AGE không thể vi phạm 1s interval nữa.
        cutoff = now - PRUNE_AGE
        for k, ts in list(self._last.items()):
            if ts < cutoff:
                del self._last[k]

    def _bound(self) -> None:
        # Bounded dict: post-insert, over cap → drop oldest.
        excess = len(self._last) - MAX_KEYS
        if excess > 0:
            for k, _ in sorted(self._last.items(), key=lambda kv: kv[1])[:excess]:
                del self._last[k]

class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._limiter = SlidingInterval()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or settings.env == "test":
            await self.app(scope, receive, send)
            return
        # ASGI path không mang query string; cap 512 như middleware.py
        if scope["path"][:512].rstrip("/") not in PROTECTED:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        ua_hash = hashlib.sha256(
            request.headers.get("user-agent", "").encode()
        ).hexdigest()
        key = f"{net.client_ip(request)}|{ua_hash}"
        if self._limiter.allow(key):
            await self.app(scope, receive, send)
            return
        await JSONResponse(status_code=429, content={"code": "rate_limited"})(
            scope, receive, send
        )
