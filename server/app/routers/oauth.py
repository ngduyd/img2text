"""Đăng nhập Google (OAuth 2.0 authorization-code).

Chỉ 2 endpoint, không thêm dependency: authorize URL dựng tay, đổi code bằng
httpx, `id_token` xác thực bằng chính endpoint `tokeninfo` của Google (Google
kiểm chữ ký, hạn, audience — không phải ta tự parse JWT).

Bật bằng env: GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET (+ OAUTH_REDIRECT_BASE
nếu app chạy sau domain khác BASE_URL). Thiếu → `/config` trả google=false,
UI ẩn nút, start/callback trả 501.

Tài khoản: tra theo (provider, sub) trước, rồi theo email (email đã tồn tại thì
liên kết, KHÔNG tạo trùng); chưa có thì tạo mới — email Google đã verify nên
is_verified=true (và bật OCR nếu đang ở chế độ tự phục vụ: chưa cấu hình SMTP).
"""

import logging
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.models import User
from app.core.security import (
    create_access_token,
    hash_password,
    set_auth_cookies,
)
from app.routers.auth import _mint_refresh, _store_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/oauth", tags=["oauth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
STATE_TTL_SECONDS = 600


def _enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _redirect_uri() -> str:
    base = (settings.oauth_redirect_base or settings.base_url).rstrip("/")
    return f"{base}/api/auth/oauth/google/callback"


def _sign_state() -> str:
    # state chống CSRF: ký bằng APP_SECRET, sống 10 phút, không lưu server-side
    return jwt.encode(
        {"n": secrets.token_urlsafe(16), "exp": int(time.time()) + STATE_TTL_SECONDS},
        settings.app_secret,
        algorithm="HS256",
    )


def _check_state(state: str) -> None:
    try:
        jwt.decode(state, settings.app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="state không hợp lệ hoặc đã hết hạn")


@router.get("/config")
async def oauth_config() -> dict:
    """UI đọc để biết có hiện nút Google hay không (không lộ secret)."""
    return {"google": _enabled()}


@router.get("/google/start")
async def google_start() -> RedirectResponse:
    if not _enabled():
        raise HTTPException(status_code=501, detail="Google OAuth chưa được cấu hình.")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": _sign_state(),
        "prompt": "select_account",
    }
    return RedirectResponse(
        f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if not _enabled():
        raise HTTPException(status_code=501, detail="Google OAuth chưa được cấu hình.")
    if error or not code or not state:
        # người dùng bấm "Huỷ" ở màn hình Google, hoặc URL thiếu tham số
        return RedirectResponse("/signin?oauth=denied", status_code=302)
    _check_state(state)

    async with httpx.AsyncClient(timeout=20) as client:
        token = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if token.status_code >= 400:
            logger.warning("oauth: đổi code thất bại %s", token.status_code)
            return RedirectResponse("/signin?oauth=failed", status_code=302)
        id_token = token.json().get("id_token")
        if not id_token:
            return RedirectResponse("/signin?oauth=failed", status_code=302)
        info = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
        if info.status_code >= 400:
            logger.warning("oauth: tokeninfo từ chối id_token %s", info.status_code)
            return RedirectResponse("/signin?oauth=failed", status_code=302)
        claims = info.json()

    # tokeninfo đã kiểm chữ ký + hạn; vẫn phải kiểm audience + email verified
    if claims.get("aud") != settings.google_client_id:
        logger.warning("oauth: aud lạ %s", claims.get("aud"))
        return RedirectResponse("/signin?oauth=failed", status_code=302)
    if str(claims.get("email_verified", "")).lower() not in ("true", "1"):
        return RedirectResponse("/signin?oauth=unverified", status_code=302)
    sub, email = claims.get("sub"), (claims.get("email") or "").lower()
    if not sub or not email:
        return RedirectResponse("/signin?oauth=failed", status_code=302)

    user = await session.scalar(
        select(User).where(User.oauth_provider == "google", User.oauth_sub == sub)
    )
    if user is None:
        user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        self_serve = settings.auto_verify_email or not settings.smtp_host
        user = User(
            email=email,
            # mật khẩu ngẫu nhiên: đăng nhập bằng OAuth, không có mật khẩu thật
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_verified=True,
            ocr_enabled=self_serve,
            tos_accepted_at=datetime.now(timezone.utc),
            tos_version=settings.tos_version,
        )
        session.add(user)
        logger.info("oauth: tạo tài khoản %s từ Google", email)
    # liên kết (idempotent) + email Google coi như đã verify
    user.oauth_provider = "google"
    user.oauth_sub = sub
    user.is_verified = True
    await session.flush()

    token_jwt = create_access_token(sub=str(user.id), role=user.role)
    refresh, jti, exp = _mint_refresh(user.id)
    _store_refresh(session, user.id, refresh, jti, exp)
    await session.commit()

    response = RedirectResponse("/jobs", status_code=302)
    set_auth_cookies(response, access=token_jwt, refresh=refresh)
    return response
