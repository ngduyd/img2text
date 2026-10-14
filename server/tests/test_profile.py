"""Tests: PATCH /api/auth/profile — self-service email/password change (Plan H Task 1)."""

import uuid

import pytest

OLD_PW = "secret123"


def _email() -> str:
    return f"p-{uuid.uuid4().hex}@test.io"


async def _register_login(client, email: str, password: str = OLD_PW) -> dict:
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_change_password_revokes_refresh_and_swaps_credentials(auth_client):
    email = _email()
    me = await _register_login(auth_client, email)
    refresh = auth_client.cookies.get("refresh")
    assert refresh is not None

    r = await auth_client.patch(
        "/api/auth/profile",
        json={"current_password": OLD_PW, "new_password": "newpass99"},
    )
    assert r.status_code == 200, r.text

    # old refresh token dead
    r = await auth_client.post("/api/auth/refresh", cookies={"refresh": refresh})
    assert r.status_code == 401, r.text
    # new password works, old fails
    r = await auth_client.post(
        "/api/auth/login", json={"email": email, "password": "newpass99"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == me["id"]  # same account
    r = await auth_client.post(
        "/api/auth/login", json={"email": email, "password": OLD_PW}
    )
    assert r.status_code == 401, r.text


async def test_change_email_swaps_login(auth_client):
    old_email = _email()
    new_email = _email()
    me = await _register_login(auth_client, old_email)

    r = await auth_client.patch(
        "/api/auth/profile",
        json={"current_password": OLD_PW, "email": new_email},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == new_email

    r = await auth_client.post(
        "/api/auth/login", json={"email": new_email, "password": OLD_PW}
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == me["id"]
    r = await auth_client.post(
        "/api/auth/login", json={"email": old_email, "password": OLD_PW}
    )
    assert r.status_code == 401, r.text


async def test_change_email_duplicate_other_user_409(client):
    email_a = _email()
    email_b = _email()
    await _register_login(client, email_a)
    await _register_login(client, email_b)

    r = await client.patch(
        "/api/auth/profile",
        json={"current_password": OLD_PW, "email": email_a},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Email đã tồn tại."


@pytest.mark.parametrize(
    "payload",
    [
        {"current_password": "wrong-pass", "new_password": "newpass99"},
        {"current_password": "wrong-pass", "email": _email()},
    ],
    ids=["password-path", "email-path"],
)
async def test_wrong_current_password_401(auth_client, payload):
    r = await auth_client.patch("/api/auth/profile", json=payload)
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Sai mật khẩu."


async def test_neither_email_nor_password_422(auth_client):
    r = await auth_client.patch(
        "/api/auth/profile", json={"current_password": OLD_PW}
    )
    assert r.status_code == 422, r.text


async def test_new_password_too_short_422(auth_client):
    r = await auth_client.patch(
        "/api/auth/profile",
        json={"current_password": OLD_PW, "new_password": "short1"},
    )
    assert r.status_code == 422, r.text


async def test_response_shape_equals_me(auth_client):
    email = _email()
    new_email = _email()
    await _register_login(auth_client, email)

    r = await auth_client.patch(
        "/api/auth/profile",
        json={"current_password": OLD_PW, "email": new_email},
    )
    assert r.status_code == 200, r.text

    me = await auth_client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert r.json() == me.json()
    assert set(r.json()) == {"id", "email", "role", "ocr_enabled", "is_verified"}
