"""Auth endpoints: register / login / me (Task 3)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.security import (
    create_access_token,
    hash_password,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    creds: Credentials, response: Response, session: AsyncSession = Depends(get_session)
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
    creds: Credentials, response: Response, session: AsyncSession = Depends(get_session)
) -> UserOut:
    user = await session.scalar(select(User).where(User.email == creds.email))
    if user is None or not verify_password(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_access_token(sub=str(user.id), role=user.role)
    set_auth_cookies(response, access=token)
    return _user_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
