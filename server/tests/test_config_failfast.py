"""P0 deploy hardening (spec 2026-10-15): prod fail-fast guards in lifespan
+ admin bootstrap. Dev/test keep placeholder defaults."""

import pytest

from app.core.config import settings
from app.main import app, lifespan
from app.services.admin_bootstrap import bootstrap_admin


async def test_prod_fails_on_default_app_secret(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "app_secret", "dev-secret-change-me")
    with pytest.raises(RuntimeError, match="app_secret"):
        async with lifespan(app):
            pass


async def test_prod_fails_on_short_app_secret(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "app_secret", "short")
    with pytest.raises(RuntimeError, match="app_secret"):
        async with lifespan(app):
            pass


async def test_prod_fails_on_default_runner_key(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "app_secret", "x" * 32)  # isolate runner_key guard
    monkeypatch.setattr(settings, "runner_key", "dev-runner-key")
    with pytest.raises(RuntimeError, match="runner_key"):
        async with lifespan(app):
            pass


async def test_dev_allows_defaults(monkeypatch):
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "app_secret", "dev-secret-change-me")
    monkeypatch.setattr(settings, "runner_key", "dev-runner-key")
    # should not raise
    async with lifespan(app):
        pass

async def test_prod_fails_on_empty_admin_creds(monkeypatch, db_session):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "admin_email", "")
    monkeypatch.setattr(settings, "admin_password", "")
    with pytest.raises(RuntimeError, match="ADMIN_EMAIL"):
        await bootstrap_admin(db_session, "", "")

async def test_dev_allows_empty_admin_creds(db_session):
    await bootstrap_admin(db_session, "", "")  # no-op, no raise
