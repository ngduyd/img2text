"""Wave-5 S6 (Lane B2): POST /api/feedback + GET /api/admin/feedbacks.

POST auth, content 1..2000 chars (pydantic → 422), page_path optional.
GET admin-only, ?page&page_size (clamp như admin users), sort created_at mới
nhất, join users để trả email.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.db import get_session
from app.core.deps import get_current_user, require_admin
from app.core.models import Feedback, User

router = APIRouter(tags=["feedback"])

class FeedbackIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    page_path: str | None = Field(default=None, max_length=500)

class FeedbackOut(BaseModel):
    id: int
    content: str
    page_path: str | None
    created_at: str

def _admin_user(user: User = Depends(get_current_user)) -> User:
    return require_admin(user)

@router.post("/api/feedback", status_code=201)
async def create_feedback(
    body: FeedbackIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    row = Feedback(user_id=user.id, content=body.content, page_path=body.page_path)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return FeedbackOut(
        id=row.id,
        content=row.content,
        page_path=row.page_path,
        created_at=row.created_at.isoformat(),
    ).model_dump()

@router.get("/api/admin/feedbacks")
async def list_feedbacks(
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(_admin_user),
) -> dict:
    """Paged feedback mới nhất; clamp page≥1, 1≤page_size≤100 (như admin users)."""
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = (await session.scalar(select(func.count()).select_from(Feedback))) or 0
    author = aliased(User)
    rows = (
        await session.execute(
            select(Feedback, author.email)
            .join(author, Feedback.user_id == author.id, isouter=True)
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": fb.id,
                "content": fb.content,
                "page_path": fb.page_path,
                "user_id": fb.user_id,
                "email": email,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            }
            for fb, email in rows
        ],
        "total": total,
    }
