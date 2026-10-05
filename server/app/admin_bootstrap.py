"""First-run admin bootstrap (Task 8, ruling R28).

Creates role='admin' user from settings.admin_email/password at startup;
no-op when credentials empty or user already exists. Trusted first identity:
bootstrap admin is created with ocr_enabled=True unconditionally.
"""

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
    # First-run must work: bootstrap admin is the trusted identity, OCR always on.
    session.add(
        User(
            email=email,
            password_hash=hash_password(password),
            role="admin",
            ocr_enabled=True,
        )
    )
    await session.commit()
