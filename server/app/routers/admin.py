"""Admin routers (Task 1): user list + ocr grant toggle."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_admin
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])

def _admin_user(user: User = Depends(get_current_user)) -> User:
    return require_admin(user)

class OcrPatch(BaseModel):
    ocr_enabled: StrictBool  # StrictBool: "yes" must 422, not coerce to True

def _user_json(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "ocr_enabled": u.ocr_enabled,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }

@router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
    page: int = 1,
    size: int = 20,
) -> dict:
    """Paged user list, id asc.

    ponytail: out-of-bounds paging CLAMPED (page≥1, 1≤size≤100) per task choice;
    switch to 422 Query(ge=..., le=...) if API strictness is ever required.
    """
    page = max(1, page)
    size = min(100, max(1, size))
    total = (await session.scalar(select(func.count()).select_from(User))) or 0
    rows = (
        await session.scalars(
            select(User).order_by(User.id).offset((page - 1) * size).limit(size)
        )
    ).all()
    return {"items": [_user_json(u) for u in rows], "total": total}

@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: OcrPatch,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.ocr_enabled = body.ocr_enabled
    await session.commit()
    return _user_json(user)
