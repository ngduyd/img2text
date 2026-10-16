"""First-run admin bootstrap (Task 8, ruling R28).

Creates role='admin' user from settings.admin_email/password at startup;
no-op when credentials empty or user already exists. Trusted first identity:
bootstrap admin is created with ocr_enabled=True unconditionally.

#16 (spec 2026-10-15):
- prod + user exists nhưng role != 'admin' → RuntimeError (privilege guard,
  fail-fast trước khi boot với identity không phải superuser)
- prod + ADMIN_PASSWORD đổi (verify_password fail) → update hash
- create/update ghi audit row RequestLog (spec cho phép reuse; path cố định
  /internal/admin-bootstrap để grep)
- non-prod existing → no-op như cũ (không surprise dev/test)
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models import RequestLog, User
from app.core.security import hash_password, password_too_long, verify_password

_AUDIT_PATH = "/internal/admin-bootstrap"

def _audit(session: AsyncSession, user_id: int | None, action: str) -> None:
    # RequestLog không có note column — action gắn qua ua (ponytail: chuyển
    # sang AuditLog model riêng khi có migration tool).
    session.add(
        RequestLog(
            method="BOOTSTRAP",
            path=_AUDIT_PATH,
            status=200,
            user_id=user_id,
            ip="internal",
            ua=action,
        )
    )

async def bootstrap_admin(session: AsyncSession, email: str, password: str) -> None:
    """Create role='admin' user; no-op when email/password empty or user
    exists (xem module docstring cho #16 prod behavior)."""
    # P0 spec 2026-10-15: prod must not boot without an admin identity.
    if settings.env == "prod" and (not email or not password):
        raise RuntimeError("prod requires ADMIN_EMAIL and ADMIN_PASSWORD")
    if not email or not password:
        return
    # QA-5: ADMIN_PASSWORD >72 byte — bcrypt cap; hash_password sẽ nổ ValueError
    # thô (traceback boot không readable) → fail-fast RuntimeError ĐỌC ĐƯỢC,
    # TRƯỚC mọi nhánh hash (create lẫn prod update-password).
    if password_too_long(password):
        raise RuntimeError(
            f"ADMIN_PASSWORD quá dài ({len(password.encode('utf-8'))} byte >72), "
            "fail-fast"
        )
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        if settings.env == "prod":
            if existing.role != "admin":
                raise RuntimeError(
                    f"admin {email} exists but is not superuser "
                    f"(role={existing.role}) — refusing prod boot"
                )
            if not verify_password(password, existing.password_hash):
                # ADMIN_PASSWORD env đổi → sync hash (#16; trước đây im lặng
                # giữ hash cũ = admin không vào được bằng env credentials)
                existing.password_hash = hash_password(password)
                _audit(session, existing.id, "update-password-from-env")
                await session.commit()
        return
    # First-run must work: bootstrap admin là trusted identity, OCR luôn on
    # + bỏ qua email-verify gate (admin bypass đã có trong middleware; đây là
    # state nhất quán từ đầu, admin không cần verify lần đầu).
    user = User(
        email=email,
        password_hash=hash_password(password),
        role="admin",
        ocr_enabled=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()  # user.id ổn định cho audit row
    _audit(session, user.id, "create-admin")
    await session.commit()
