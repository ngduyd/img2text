"""Auth dependencies (Task 3)."""

import hmac
import warnings

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User

ACCESS_COOKIE = "access"
REFRESH_COOKIE = "refresh"


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
        raise HTTPException(status_code=403, detail="ocr not enabled")
    return user


def get_runner_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    scheme, _, key = auth.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        key, settings.runner_key
    ):
        raise HTTPException(status_code=401, detail="bad runner key")
    return key
