"""Auth dependencies (Task 3): current-user/admin/ocr gates + runner key.

Rulings embedded: 401/403 detail strings are test-pinned contract;
get_runner_key is R11's bearer capability-token check for worker endpoints.
get_session_key (spec kaggle session worker T3): per-session Bearer key —
anti-oracle 401 "bad session key" cho mọi lỗi + rate-limit per-IP.
"""

import hmac
import warnings

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.models import User, WorkerSession
from app.core.net import client_ip

ACCESS_COOKIE = "access"
REFRESH_COOKIE = "refresh"

# Spec kaggle session worker T3: 60 req/phút/IP cho session-key endpoints
# (worker poll + claim). Floor sống trong constant — không runtime setting.
# ponytail: in-process SlidingWindow — single-worker assumption (cùng
# upload_limiter); multi-worker deploy → DB/Redis-backed.
SESSION_AUTH_LIMIT = 60
SESSION_AUTH_WINDOW_SECONDS = 60


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        # ponytail: dev secret 20 bytes < RFC 7518 minimum; same suppress as
        # security.create_access_token until deploy sets longer secret
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
            payload = jwt.decode(
                token, settings.app_secret, algorithms=["HS256"], issuer="img2text"
            )
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="not authenticated")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_admin(user: User) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user


def require_ocr(user: User) -> User:
    if not user.ocr_enabled:
        raise HTTPException(status_code=403, detail="Chưa được cấp quyền OCR.")
    return user


def get_runner_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    scheme, _, key = auth.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not key.isascii()  # compare_digest TypeError → 500 on non-ascii
        or not hmac.compare_digest(key, settings.runner_key)
    ):
        raise HTTPException(status_code=401, detail="bad runner key")
    return key

async def get_session_key(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> str:
    """Kaggle session worker auth (spec 2026-10-16 T3): Bearer = plaintext
    session key (1 lần khi claim); lookup sha256 hash-at-rest + live row
    (closed_at IS NULL). Mọi lỗi (thiếu header/sai scheme/key lạ/session
    đóng) → 401 CÙNG detail rỗng (anti-oracle — không phân biệt nguyên nhân).
    Non-ascii key → 401 (hash_worker_token bytes(key) UnicodeEncodeError
    pattern deps.get_runner_key). Rate-limit per-IP 60/phút trước DB."""
    from app.core.limiter import SlidingWindow  # lazy: limiter imports deps
    from app.core.security import hash_worker_token  # lazy: security imports deps
    limiter = getattr(request.app.state, "session_auth_limiter", None)
    if limiter is None:
        limiter = request.app.state.session_auth_limiter = SlidingWindow(
            SESSION_AUTH_LIMIT, SESSION_AUTH_WINDOW_SECONDS
        )
    if not limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu.")
    auth = request.headers.get("Authorization", "")
    scheme, _, key = auth.partition(" ")
    if scheme.lower() != "bearer" or not key or not key.isascii():
        raise HTTPException(status_code=401, detail="bad session key")
    live = await session.scalar(
        select(WorkerSession.id).where(
            WorkerSession.key_hash == hash_worker_token(key),
            WorkerSession.closed_at.is_(None),
        )
    )
    if live is None:
        raise HTTPException(status_code=401, detail="bad session key")
    return key
