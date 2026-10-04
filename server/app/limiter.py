"""Sliding-window rate limiter for auth endpoints (Task 6).

ponytail: single-process in-memory dict; multi-worker deploy → move to
Postgres (or Redis) before scale.
"""

import time
from collections import deque

from fastapi import HTTPException, Request

from app.net import client_ip

AUTH_LIMIT = 10
AUTH_WINDOW_SECONDS = 3600


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


async def rate_limit_auth(request: Request) -> None:
    # lazy per-app instance: one limiter per create_app() (fresh per test
    # client); production app keeps one for the process lifetime
    limiter = getattr(request.app.state, "auth_limiter", None)
    if limiter is None:
        limiter = request.app.state.auth_limiter = SlidingWindow(AUTH_LIMIT, AUTH_WINDOW_SECONDS)
    if not limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu.")
