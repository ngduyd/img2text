"""Task 8: admin bootstrap (probe route removed in Task 1)."""

from sqlalchemy import select

from app.services.admin_bootstrap import bootstrap_admin
from app.core.models import User


async def test_bootstrap_admin_creates_admin_and_is_idempotent(db_session):
    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    u = (
        await db_session.execute(select(User).where(User.email == "admin@x.io"))
    ).scalar_one()
    assert u.role == "admin"
    # Task: first-run upload path — bootstrap admin is OCR-enabled.
    assert u.ocr_enabled is True
    # Admin bootstrap bỏ qua verify gate — trusted first identity.
    assert u.is_verified is True

    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    rows = (
        await db_session.execute(select(User).where(User.email == "admin@x.io"))
    ).scalars().all()
    assert len(rows) == 1


async def test_bootstrap_admin_noop_on_empty_email(db_session):
    await bootstrap_admin(db_session, "", "whatever")
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 0

# --- #16 (spec 2026-10-15): prod password sync + privilege guard + audit ---

import pytest

from app.core.config import settings
from app.core.models import RequestLog
from app.core.security import hash_password, verify_password


async def test_prod_updates_admin_password_on_env_change(db_session, monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    # bootstrap đọc email/password từ ARG (spec test monkeypatch settings —
    # function không nhận settings.admin_*; cùng giả định, cùng assertion)
    await bootstrap_admin(db_session, "admin@test.com", "old-pass")
    user = await db_session.scalar(
        select(User).where(User.email == "admin@test.com")
    )
    assert verify_password("old-pass", user.password_hash)

    # ADMIN_PASSWORD env đổi → lần bootstrap sau sync hash
    await bootstrap_admin(db_session, "admin@test.com", "new-pass")
    await db_session.refresh(user)
    assert verify_password("new-pass", user.password_hash)
    # audit row cho password update
    audit = (
        await db_session.execute(
            select(RequestLog).where(RequestLog.path == "/internal/admin-bootstrap")
        )
    ).scalars().all()
    assert any(r.ua == "update-password-from-env" for r in audit)


async def test_prod_raises_on_existing_non_superuser_admin(db_session, monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    db_session.add(
        User(email="admin@test.com", password_hash=hash_password("x"), role="user")
    )
    await db_session.commit()
    with pytest.raises(RuntimeError, match="admin.*not superuser"):
        await bootstrap_admin(db_session, "admin@test.com", "pass")


async def test_bootstrap_creates_audit_log_row(db_session):
    await bootstrap_admin(db_session, "aud@test.com", "adminpass1")
    u = await db_session.scalar(select(User).where(User.email == "aud@test.com"))
    row = await db_session.scalar(
        select(RequestLog).where(RequestLog.path == "/internal/admin-bootstrap")
    )
    assert row is not None and row.method == "BOOTSTRAP"
    assert row.user_id == u.id and row.ua == "create-admin"


async def test_non_prod_existing_admin_ignores_new_password(db_session):
    """Non-prod: existing → no-op như cũ (không verify, không update) —
    dev/test không surprise bị đổi hash vì args khác."""
    await bootstrap_admin(db_session, "np@test.com", "first-pass-1")
    u = await db_session.scalar(select(User).where(User.email == "np@test.com"))
    before = u.password_hash
    await bootstrap_admin(db_session, "np@test.com", "other-pass-2")
    await db_session.refresh(u)
    assert u.password_hash == before
