"""Admin bootstrap (Task 8)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import hash_password


async def bootstrap_admin(session: AsyncSession, email: str, password: str) -> None:
    """Create role='admin' user; no-op when email/password empty or user
    exists."""
    if not email or not password:
        return
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        return
    session.add(User(email=email, password_hash=hash_password(password), role="admin"))
    await session.commit()
