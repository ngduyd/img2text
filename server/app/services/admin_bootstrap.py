"""First-run admin bootstrap (Task 8, ruling R28).

Creates role='admin' user from settings.admin_email/password at startup;
no-op when credentials empty or user already exists. Trusted first identity:
bootstrap admin is created with ocr_enabled=True unconditionally.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models import User
from app.core.security import hash_password


async def bootstrap_admin(session: AsyncSession, email: str, password: str) -> None:
    """Create role='admin' user; no-op when email/password empty or user
    exists."""
    # P0 spec 2026-10-15: prod must not boot without an admin identity.
    if settings.env == "prod" and (not email or not password):
        raise RuntimeError("prod requires ADMIN_EMAIL and ADMIN_PASSWORD")
    if not email or not password:
        return
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        return
    # First-run must work: bootstrap admin is the trusted identity, OCR always on
    # + bỏ qua email-verify gate (admin bypass đã có trong middleware; đây là
    # state nhất quán từ đầu, admin không cần verify lần đầu).
    session.add(
        User(
            email=email,
            password_hash=hash_password(password),
            role="admin",
            ocr_enabled=True,
            is_verified=True,
        )
    )
    await session.commit()
