"""Sliding-window rate limiter for auth endpoints (Task 6).

ponytail: single-process in-memory dict; multi-worker deploy → move to
Postgres (or Redis) before scale.
"""

import time
from collections import deque
from datetime import date

from fastapi import HTTPException, Request

from app.core.deps import ACCESS_COOKIE
from app.core.net import client_ip
from app.core.security import decode_access_sub

AUTH_LIMIT = 10
AUTH_WINDOW_SECONDS = 3600

# P2 #20 (spec 2026-10-16): per-user windows cho feedback + upload.
FEEDBACK_LIMIT = 10
FEEDBACK_WINDOW_SECONDS = 60
UPLOAD_HOURLY_LIMIT = 30
UPLOAD_WINDOW_SECONDS = 3600


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> bool:
        """True = allowed, False = limited. Lazy eviction + expired-key prune
        bounds memory on every check."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        for k, hits in list(self._hits.items()):
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[k]
        hits = self._hits.setdefault(key, deque())
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class DailyCounter:
    """Calendar-day (midnight local) counter per key, for upload limits.

    ponytail: same ceiling as SlidingWindow — single-process in-memory dict;
    multi-worker deploy → move to Postgres (or Redis) before scale.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._days: dict[str, tuple[date, int]] = {}

    def check(self, key: str) -> bool:
        """True = allowed, False = limited. Lazy same-day prune bounds memory."""
        today = date.today()
        for k, (day, _) in list(self._days.items()):
            if day != today:
                del self._days[k]
        count = self._days.get(key, (today, 0))[1]
        if count >= self.limit:
            return False
        self._days[key] = (today, count + 1)
        return True

async def rate_limit_auth(request: Request) -> None:
    # lazy per-app instance: one limiter per create_app() (fresh per test
    # client); production app keeps one for the process lifetime
    limiter = getattr(request.app.state, "auth_limiter", None)
    if limiter is None:
        limiter = request.app.state.auth_limiter = SlidingWindow(AUTH_LIMIT, AUTH_WINDOW_SECONDS)
    if not limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu.")

def _per_user_key(request: Request) -> str:
    """P2 #20: key per-user (access cookie JWT sub); anonymous → fallback
    theo IP (endpoint auth đều đi qua get_current_user nên nhánh IP chỉ
    là safety net)."""
    sub = decode_access_sub(request.cookies.get(ACCESS_COOKIE, ""))
    return f"user:{sub}" if sub is not None else f"ip:{client_ip(request)}"

async def rate_limit_feedback(request: Request) -> None:
    """P2 #20: 10 feedback/phút per user → 429."""
    limiter = getattr(request.app.state, "feedback_limiter", None)
    if limiter is None:
        limiter = request.app.state.feedback_limiter = SlidingWindow(
            FEEDBACK_LIMIT, FEEDBACK_WINDOW_SECONDS
        )
    if not limiter.check(_per_user_key(request)):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu.")

async def rate_limit_upload(request: Request) -> None:
    """P2 #20: 30 upload/giờ per user → 429 (song song daily counter
    trong jobs.create_job — 2 tầng độc lập)."""
    limiter = getattr(request.app.state, "upload_hourly_limiter", None)
    if limiter is None:
        limiter = request.app.state.upload_hourly_limiter = SlidingWindow(
            UPLOAD_HOURLY_LIMIT, UPLOAD_WINDOW_SECONDS
        )
    if not limiter.check(_per_user_key(request)):
        raise HTTPException(status_code=429, detail="Đã đạt giới hạn upload (30/giờ).")
