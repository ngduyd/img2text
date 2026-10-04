"""Auth endpoints: register / login / me / refresh / logout (Task 3+4)."""

import hashlib
import warnings
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import mailer
from app.config import settings
from app.db import get_session
from app.deps import get_current_user
from app.limiter import rate_limit_auth
from app.models import PasswordResetToken, RefreshToken, User
from app.security import (
    JWT_ISSUER,
    create_access_token,
    generate_reset_token,
    hash_password,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_REFRESH_TTL = timedelta(days=30)
_RESET_TTL = timedelta(hours=1)
REFRESH_COOKIE = "refresh"


def _mint_refresh(user_id: int) -> tuple[str, UUID, datetime]:
    now = datetime.now(timezone.utc)
    jti = uuid4()
    exp = now + _REFRESH_TTL
    payload = {
        "sub": str(user_id),
        "jti": str(jti),
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": exp,
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
        token = jwt.encode(payload, settings.app_secret, algorithm="HS256")
    return token, jti, exp


def _decode_refresh(token: str) -> tuple[int, UUID] | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
            payload = jwt.decode(
                token, settings.app_secret, algorithms=["HS256"], issuer=JWT_ISSUER
            )
        return int(payload["sub"]), UUID(payload["jti"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def _store_refresh(
    session: AsyncSession, user_id: int, token: str, jti: UUID, exp: datetime
) -> None:
    session.add(
        RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=exp,
        )
    )


class Credentials(BaseModel):
    # ponytail: regex format check; upgrade to EmailStr + email-validator when
    # deploy needs stricter RFC validation
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    ocr_enabled: bool


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, role=user.role, ocr_enabled=user.ocr_enabled
    )


@router.post("/register", status_code=201, response_model=UserOut)
async def register(
    creds: Credentials,
    response: Response,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> UserOut:
    existing = await session.scalar(select(User).where(User.email == creds.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    user = User(email=creds.email, password_hash=hash_password(creds.password))
    session.add(user)
    await session.commit()
    token = create_access_token(sub=str(user.id), role=user.role)
    set_auth_cookies(response, access=token)
    return _user_out(user)


@router.post("/login", response_model=UserOut)
async def login(
    creds: Credentials,
    response: Response,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> UserOut:
    user = await session.scalar(select(User).where(User.email == creds.email))
    if user is None or not verify_password(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_access_token(sub=str(user.id), role=user.role)
    # Task 3 ponytail deferred refresh-cookie plumbing to Task 4: mint+store
    # refresh at login so the session has a rotatable refresh token.
    # ponytail: register does not set a refresh cookie; add when a client
    # needs a session straight from registration.
    refresh, jti, exp = _mint_refresh(user.id)
    _store_refresh(session, user.id, refresh, jti, exp)
    await session.commit()
    set_auth_cookies(response, access=token, refresh=refresh)
    return _user_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Rotate refresh token. Reuse of a used jti revokes the whole family."""
    token = request.cookies.get(REFRESH_COOKIE)
    decoded = _decode_refresh(token) if token is not None else None
    if decoded is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user_id, jti = decoded
    row = await session.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=401, detail="not authenticated")
    now = datetime.now(timezone.utc)
    if row.used_at is not None:
        # reuse detection: token replayed → revoke every refresh token for user
        await session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == row.user_id)
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="not authenticated")
    if row.expires_at <= now:
        raise HTTPException(status_code=401, detail="not authenticated")
    # atomic rotation claim: conditional UPDATE closes the check-then-set race
    # (two concurrent refreshes with same jti); rowcount 0 → concurrent claim
    # won → treat as reuse → revoke family
    claim = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == jti, RefreshToken.used_at.is_(None))
        .values(used_at=now)
    )
    if claim.rowcount != 1:
        await session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == row.user_id)
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="not authenticated")
    new_token, new_jti, exp = _mint_refresh(user_id)
    _store_refresh(session, user_id, new_token, new_jti, exp)
    await session.commit()
    user = await session.get(User, user_id)
    new_access = create_access_token(sub=str(user.id), role=user.role)
    set_auth_cookies(response, access=new_access, refresh=new_token)
    return {}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    token = request.cookies.get(REFRESH_COOKIE)
    decoded = _decode_refresh(token) if token is not None else None
    if decoded is not None:
        await session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == decoded[0])
        )
        await session.commit()
    response.delete_cookie("access", path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return {}

class ForgotIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8)

@router.post("/password/forgot", status_code=202)
async def forgot(
    body: ForgotIn,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> dict:
    """Always 202 {} — identical body for known/unknown email (no user
    enumeration). If the user exists: store sha256(raw) token, email the raw
    link. send_email never raises (mailer swallows SMTP failures)."""
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is not None:
        raw = generate_reset_token()
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=datetime.now(timezone.utc) + _RESET_TTL,
            )
        )
        await session.commit()
        await mailer.send_email(
            user.email,
            "Reset your password",
            f"Reset your password: {settings.base_url}/reset?token={raw}\n"
            "If you did not request this, ignore this email.",
        )
    return {}

@router.post("/password/reset")
async def reset(
    body: ResetIn, session: AsyncSession = Depends(get_session)
) -> dict:
    """Consume reset token (single-use), rehash password, revoke ALL refresh
    tokens. Invalid/expired/used token → 422."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    # atomic single-use claim: WHERE used_at IS NULL AND not expired —
    # concurrent resets with same token → one winner, rest get rowcount 0
    claim = await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if claim.rowcount != 1:
        raise HTTPException(status_code=422, detail="invalid or expired token")
    row = await session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    user = await session.get(User, row.user_id)
    user.password_hash = hash_password(body.password)
    await session.execute(
        delete(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    await session.commit()
    return {}
