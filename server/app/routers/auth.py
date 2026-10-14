"""Auth endpoints: register / login / me / refresh / logout (Task 3+4)."""

import hashlib
import hmac
import warnings
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import email_sends, mailer
from app.core.config import settings
from app.core.db import get_session
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_current_user
from app.core.limiter import rate_limit_auth
from app.core.models import RefreshToken, User
from app.core.security import (
    JWT_ISSUER,
    create_access_token,
    generate_email_code,
    hash_email_code,
    hash_password,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_REFRESH_TTL = timedelta(days=30)
# S5: mã verify/reset 6 số TTL 5 phút (single active code/user, ghi đè)
_EMAIL_CODE_TTL = timedelta(minutes=5)


# Deviation from plan Task 3 interface: refresh minting is a private 3-tuple
# helper here instead of an exported security.create_refresh_token; nothing
# consumes the plan's name.
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


class _EmailIn(BaseModel):
    """Shared email input normalized case-insensitively (spec §4) before any
    DB use; the unique constraint stays case-sensitive until a citext/DB-level
    migration lands (Alembic, later)."""

    @field_validator("email", mode="before", check_fields=False)
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        # isinstance guard: non-str input falls through to pattern/type
        # validation → 422, never AttributeError → 500
        return v.strip().lower() if isinstance(v, str) else v


async def revoke_all_refresh(session: AsyncSession, user_id: int) -> None:
    """Delete every refresh token row for user + commit. Ruling R50: exported
    so profile.py shares the logic instead of duplicating it."""
    await session.execute(
        delete(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    await session.commit()

class Credentials(_EmailIn):
    # ponytail: regex format check; upgrade to EmailStr + email-validator when
    # deploy needs stricter RFC validation
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    ocr_enabled: bool
    # S5: gating 403 email_unverified đọc state này (web route guard)
    is_verified: bool


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        ocr_enabled=user.ocr_enabled,
        is_verified=user.is_verified,
    )


@router.post("/register", status_code=201, response_model=UserOut)
async def register(
    creds: Credentials,
    response: Response,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> UserOut:
    """S5: luôn 201, không leak tồn tại — email đã đăng ký → body decoy
    (id=0), KHÔNG cookie, KHÔNG email (chống email-bomb tài khoản thật).

    User mới: is_verified=false → send welcome + verify-code email (mã 6 số
    TTL 5p, hash lưu DB). User vừa tạo → 2 kind đều là lần #1 trong window,
    quota không thể vượt — bỏ check, record rồi commit chung."""
    existing = await session.scalar(select(User).where(User.email == creds.email))
    if existing is not None:
        return UserOut(
            id=0, email=creds.email, role="user", ocr_enabled=False, is_verified=False
        )
    user = User(email=creds.email, password_hash=hash_password(creds.password))
    session.add(user)
    await session.commit()  # id ổn định cho email_sends + code hash
    code = generate_email_code()
    user.email_verify_code_hash = hash_email_code(user.email, code)
    user.email_verify_expires_at = datetime.now(timezone.utc) + _EMAIL_CODE_TTL
    email_sends.record(session, user.id, "welcome")
    email_sends.record(session, user.id, "verify_code")
    await session.commit()
    background_tasks.add_task(
        mailer.send_email,
        user.email,
        "Welcome to img2text",
        "Welcome to img2text.\n\n"
        "Your account is created. Use the 6-digit code we just emailed you "
        "to verify your email — until then only login, register and "
        "password-reset endpoints work.\n\n"
        "If you did not create this account, ignore this email.\n",
    )
    background_tasks.add_task(
        mailer.send_email,
        user.email,
        "Verify your email",
        _verify_email_body(code),
    )
    token = create_access_token(sub=str(user.id), role=user.role)
    set_auth_cookies(response, access=token)
    return _user_out(user)

def _verify_email_body(code: str) -> str:
    return (
        f"Your email verification code is: {code}\n\n"
        "It expires in 5 minutes. If you did not request this, "
        "ignore this email.\n"
    )

class CodeIn(BaseModel):
    # S5: mã 6 số — check format ở boundary; khác format → 422
    code: str = Field(pattern=r"^\d{6}$")

@router.post("/verify")
async def verify_email(
    body: CodeIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_auth),
) -> dict:
    """S5: hash compare + TTL 5p — sai/hết hạn → 422. Đúng →
    is_verified=true, xóa code (single-use). Gated user gọi được (exempt)."""
    now = datetime.now(timezone.utc)
    if (
        user.email_verify_code_hash is None
        or user.email_verify_expires_at is None
        or user.email_verify_expires_at <= now
        or not hmac.compare_digest(
            user.email_verify_code_hash, hash_email_code(user.email, body.code)
        )
    ):
        raise HTTPException(status_code=422, detail="invalid or expired code")
    user.is_verified = True
    user.email_verify_code_hash = None
    user.email_verify_expires_at = None
    await session.commit()
    return {}

@router.post("/verify/resend", status_code=202)
async def verify_resend(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_auth),
) -> dict:
    """S5: code MỚI ghi đè code cũ (single active/user); qua per-kind
    email limit — vượt → 429 email_limit (handler ở main.py).

    P2 review: đã verified → 400 {code:"already_verified"}, KHÔNG gửi
    email (không dùng resend làm kênh email-bomb)."""
    if user.is_verified:
        return JSONResponse(
            status_code=400, content={"code": "already_verified"}
        )
    await email_sends.check_limit(session, user.id, "verify_code")
    code = generate_email_code()
    user.email_verify_code_hash = hash_email_code(user.email, code)
    user.email_verify_expires_at = datetime.now(timezone.utc) + _EMAIL_CODE_TTL
    email_sends.record(session, user.id, "verify_code")
    await session.commit()
    background_tasks.add_task(
        mailer.send_email, user.email, "Verify your email", _verify_email_body(code)
    )
    return {}


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
        await revoke_all_refresh(session, row.user_id)
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
        await revoke_all_refresh(session, row.user_id)
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
        await revoke_all_refresh(session, decoded[0])
    # ponytail: access-only client revokes nothing (stateless access ≤15m);
    # upgrade path: access-jwt sub fallback for identification once a
    # server-side access store exists.
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return {}


class ForgotIn(_EmailIn):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResetIn(_EmailIn):
    # P1-3 review: body có email — lookup per-user theo email rồi mới
    # so sánh hash; rate_limit_auth + TTL 5p chặn brute force
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8)


@router.post("/password/forgot", status_code=202)
async def forgot(
    body: ForgotIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> dict:
    """Luôn 202 {} cho email không tồn tại (không enumeration). Known →
    mã 6 số TTL 5p (hash lưu users.password_reset_code; single active code
    — ghi đè), qua per-kind email limit — check TRƯỚC enqueue; vượt →
    429 email_limit (leak tồn tại chấp nhận để chặn spam).

    SMTP enqueue SAU commit; mailer tự swallow lỗi → không 500."""
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None:
        return {}
    await email_sends.check_limit(session, user.id, "reset_code")
    code = generate_email_code()
    user.password_reset_code = hash_email_code(user.email, code)
    user.password_reset_expires_at = datetime.now(timezone.utc) + _EMAIL_CODE_TTL
    email_sends.record(session, user.id, "reset_code")
    await session.commit()
    background_tasks.add_task(
        mailer.send_email,
        user.email,
        "Reset your password",
        f"Your password reset code is: {code}\n\n"
        "It expires in 5 minutes. If you did not request this, "
        "ignore this email.\n",
    )
    return {}


@router.post("/password/reset")
async def reset(
    body: ResetIn,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limit_auth),
) -> dict:
    """S5+P1-3: {email, code, password} — lookup user theo email, so hash
    per-user (sha256(email:code:secret)) + chưa hết hạn trong MỘT conditional
    UPDATE ... RETURNING (atomic claim — không check-then-set race).
    0 match → 422. Đúng → đổi mật khẩu + revoke ALL refresh CÙNG transaction
    (single commit; code single-use vì đã NULL claim)."""
    now = datetime.now(timezone.utc)
    claim = await session.execute(
        update(User)
        .where(
            User.id
            == select(User.id)
            .where(User.email == body.email)
            .scalar_subquery(),
            User.password_reset_code == hash_email_code(body.email, body.code),
            User.password_reset_expires_at > now,
        )
        .values(
            password_reset_code=None,
            password_reset_expires_at=None,
            password_hash=hash_password(body.password),
        )
        .returning(User.id),
    )
    user_id = claim.scalar_one_or_none()
    if user_id is None:
        await session.rollback()
        raise HTTPException(status_code=422, detail="invalid or expired code")
    await session.execute(
        delete(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    await session.commit()
    return {}
