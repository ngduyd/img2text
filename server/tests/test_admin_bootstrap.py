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

    await bootstrap_admin(db_session, "admin@x.io", "adminpass1")
    rows = (
        await db_session.execute(select(User).where(User.email == "admin@x.io"))
    ).scalars().all()
    assert len(rows) == 1


async def test_bootstrap_admin_noop_on_empty_email(db_session):
    await bootstrap_admin(db_session, "", "whatever")
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 0
