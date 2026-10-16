"""PATCH /api/auth/profile — self-service email/password change (Plan H Task 1).

Same shape as /me; current_password always required; at least one of
email/new_password required. Password change revokes every refresh token
(ruling R50 helper shared with auth.py reset/logout).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_user
from app.core.limiter import rate_limit_auth
from app.core.models import User
from app.routers.auth import UserOut, _EmailIn, _user_out, revoke_all_refresh
from app.core.security import hash_password, password_too_long, verify_password

router = APIRouter(prefix="/api/auth", tags=["profile"])

class ProfileIn(_EmailIn):
    # _EmailIn normalizes email (strip().lower()); pattern matches Credentials
    current_password: str
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    new_password: str | None = Field(default=None, min_length=8)

    @model_validator(mode="after")
    def _at_least_one_change(self) -> "ProfileIn":
        if self.email is None and self.new_password is None:
            raise ValueError("email or new_password required")
        return self

@router.patch("/profile", response_model=UserOut)
async def update_profile(
    body: ProfileIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_auth),  # bcrypt verify per request; no brute-force surface
) -> UserOut:
    #11: password >72 byte → 400 boundary TRƯỚC (bcrypt cap — kể cả sai
    # current_password cũng không được hash).
    if password_too_long(body.new_password or ""):
        return JSONResponse(
            status_code=400,
            content={"code": "password_too_long", "max_bytes": 72},
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Sai mật khẩu.")
    if body.email is not None and body.email != user.email:
        existing = await session.scalar(
            select(User).where(User.email == body.email)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email đã tồn tại.")
        user.email = body.email
    if body.new_password is not None:
        user.password_hash = hash_password(body.new_password)
        await revoke_all_refresh(session, user.id)
    await session.commit()
    return _user_out(user)
