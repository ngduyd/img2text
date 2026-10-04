"""Task 5: password forgot/reset via SMTP.

Ruling R2: tests extract the raw reset token from the captured email body
(regex on the link); token_hash in DB stays sha256(raw). No hash monkeypatching.
"""

import re

import pytest_asyncio

from app.db import Base, engine

@pytest_asyncio.fixture(autouse=True)
async def _create_tables():
    # ponytail: create_all per test until conftest owns schema bootstrapping
    # (same pattern as test_models.py).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

def _capture():
    """Monkeypatch target: app.mailer.send_email (route calls via module)."""
    sent = []

    async def fake(to, subject, body):
        sent.append((to, subject, body))

    return sent, fake

def _token_from(sent) -> str:
    to, subject, body = sent[-1]
    m = re.search(r"token=([A-Za-z0-9_-]+)", body)
    assert m, f"no token in email body: {body!r}"
    return m.group(1)

async def test_forgot_identical_response(client, monkeypatch):
    sent, fake = _capture()
    monkeypatch.setattr("app.mailer.send_email", fake)
    await client.post("/api/auth/register", json={"email": "p@x.io", "password": "secret123"})
    r1 = await client.post("/api/auth/password/forgot", json={"email": "p@x.io"})
    r2 = await client.post("/api/auth/password/forgot", json={"email": "nobody@x.io"})
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    assert [to for to, _, _ in sent] == ["p@x.io"]

async def test_reset_changes_password_and_revokes(client, monkeypatch):
    sent, fake = _capture()
    monkeypatch.setattr("app.mailer.send_email", fake)
    await client.post("/api/auth/register", json={"email": "q@x.io", "password": "secret123"})
    await client.post("/api/auth/login", json={"email": "q@x.io", "password": "secret123"})
    assert client.cookies.get("refresh")  # session has a refresh token to revoke
    await client.post("/api/auth/password/forgot", json={"email": "q@x.io"})
    token = _token_from(sent)
    r = await client.post("/api/auth/password/reset", json={"token": token, "password": "newsecret1"})
    assert r.status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 401  # all refresh tokens revoked
    assert (await client.post("/api/auth/login", json={"email": "q@x.io", "password": "newsecret1"})).status_code == 200
    assert (await client.post("/api/auth/login", json={"email": "q@x.io", "password": "secret123"})).status_code == 401

async def test_reset_invalid_token_422(client):
    r = await client.post("/api/auth/password/reset", json={"token": "nope", "password": "newsecret1"})
    assert r.status_code == 422

async def test_used_token_cannot_be_reused(client, monkeypatch):
    sent, fake = _capture()
    monkeypatch.setattr("app.mailer.send_email", fake)
    await client.post("/api/auth/register", json={"email": "s@x.io", "password": "secret123"})
    await client.post("/api/auth/password/forgot", json={"email": "s@x.io"})
    token = _token_from(sent)
    r1 = await client.post("/api/auth/password/reset", json={"token": token, "password": "newsecret1"})
    assert r1.status_code == 200
    r2 = await client.post("/api/auth/password/reset", json={"token": token, "password": "another99"})
    assert r2.status_code == 422
