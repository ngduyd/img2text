"""Password hashing, JWT minting, cookie helpers (Task 3).

bcrypt used directly (not passlib): bcrypt 5.x + passlib 1.7.4 log a
`__about__` AttributeError that pollutes test output.
"""

import os

import hashlib
import warnings
from datetime import datetime, timedelta, timezone
import secrets
import warnings

import bcrypt
import jwt
from fastapi import Response

from app.core.config import settings
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE

# 12 = production; test hạ xuống 4 qua env BCRYPT_ROUNDS (hash 0,25 s → 5 ms).
_BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))
# #11: bcrypt truncates tại 72 byte — cap phải sống cạnh rounds (một chỗ cho
# mọi consumer; API boundary đọc cùng constant)
BCRYPT_MAX_BYTES = 72
JWT_ISSUER = "img2text"
_ACCESS_TTL = timedelta(minutes=15)


def password_too_long(p: str) -> bool:
    """#11 (spec 2026-10-15): bcrypt CẮT input ở 72 byte — hai password khác
    nhau cùng tiền tố 72B hash giống nhau. UTF-8 byte count, không đếm ký tự.
    Dùng ở hash_password (ValueError) + API boundary (400 flat)."""
    return len(p.encode("utf-8")) > BCRYPT_MAX_BYTES

def hash_password(p: str) -> str:
    if password_too_long(p):
        raise ValueError(
            f"password too long: {len(p.encode('utf-8'))} bytes "
            f"> bcrypt cap {BCRYPT_MAX_BYTES}"
        )
    return bcrypt.hashpw(
        p.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    ).decode()


def hash_worker_token(token: str) -> str:
    """P2 #16: worker_token hash-at-rest — DB chỉ chứa sha256 hex;
    plaintext trả về worker đúng 1 lần khi claim (next_job)."""
    return hashlib.sha256(token.encode()).hexdigest()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def decode_access_sub(token: str) -> int | None:
    """Access-JWT sub → int user_id; None on any failure (Ruling R6:
    logging middleware logs anonymously, never raises)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
            payload = jwt.decode(
                token, settings.app_secret, algorithms=["HS256"], issuer=JWT_ISSUER
            )
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def create_access_token(sub: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + _ACCESS_TTL,
    }
    # ponytail: dev secret is 20 bytes < RFC 7518 32-byte minimum for HS256;
    # longer secret set at deploy via env. Warnings-as-errors otherwise breaks
    # pytest -W error. Upgrade: raise default dev secret once Task 4 lands.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", jwt.InsecureKeyLengthWarning)
        return jwt.encode(payload, settings.app_secret, algorithm="HS256")


def _cookie_secure() -> bool:
    return str(settings.base_url).startswith("https")


def generate_email_code() -> str:
    """Mã 6 số (000000-999999) cho email verify / password reset (S5)."""
    return f"{secrets.randbelow(1_000_000):06d}"

def hash_email_code(email: str, code: str) -> str:
    """sha256 hex per-user — salt = email + app_secret (P1-3 review):
    hash = sha256(f"{email}:{code}:{settings.app_secret}"). Lookup/reset
    identify the user by email FIRST, then compare with hmac.compare_digest
    — DB chỉ lưu hash."""
    return hashlib.sha256(f"{email}:{code}:{settings.app_secret}".encode()).hexdigest()


def set_auth_cookies(response: Response, access: str, refresh: str | None = None) -> None:
    """Set auth cookies. Refresh-cookie plumbing lands in Task 4
    (ponytail: pass-through only; no refresh minting/storage here)."""
    response.set_cookie(
        ACCESS_COOKIE, access,
        httponly=True, samesite="lax", path="/", secure=_cookie_secure(),
    )
    if refresh is not None:
        response.set_cookie(
            REFRESH_COOKIE, refresh,
            httponly=True, samesite="lax", path="/", secure=_cookie_secure(),
        )
