import os
from fastapi import status


def test_register_login_me_flow(client):
    """Test full registration, login, and get_me lifecycle."""
    # 1. Register a new learner
    register_payload = {
        "name": "Alice Learner",
        "email": "alice@learnwise.com",
        "password": "SecurePassword123!",
        "role": "learner",
    }
    reg_response = client.post("/api/auth/register", json=register_payload)
    assert reg_response.status_code == status.HTTP_201_CREATED
    reg_data = reg_response.json()
    assert reg_data["email"] == "alice@learnwise.com"
    assert reg_data["name"] == "Alice Learner"
    assert reg_data["role"] == "learner"
    assert "created_at" in reg_data
    assert reg_data["created_at"] is not None

    # 2. Login
    login_payload = {
        "email": "alice@learnwise.com",
        "password": "SecurePassword123!",
    }
    login_response = client.post("/api/auth/login", json=login_payload)
    assert login_response.status_code == status.HTTP_200_OK
    login_data = login_response.json()
    assert "access_token" in login_data
    assert login_data["token_type"] == "bearer"

    token = login_data["access_token"]

    # 3. /api/auth/me
    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == status.HTTP_200_OK
    me_data = me_response.json()
    assert me_data["id"] == reg_data["id"]
    assert me_data["email"] == "alice@learnwise.com"
    assert me_data["role"] == "learner"
    assert "created_at" in me_data


def test_duplicate_email_registration_returns_400(client):
    """Registering an account with an existing email returns 400 Bad Request."""
    payload = {
        "name": "Bob Duplicate",
        "email": "bob@learnwise.com",
        "password": "Password123!",
        "role": "learner",
    }
    first_resp = client.post("/api/auth/register", json=payload)
    assert first_resp.status_code == status.HTTP_201_CREATED

    second_resp = client.post("/api/auth/register", json=payload)
    assert second_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "already registered" in second_resp.json()["detail"].lower()


def test_login_wrong_password_returns_401(client):
    """Logging in with an incorrect password returns 401 Unauthorized."""
    payload = {
        "name": "Charlie User",
        "email": "charlie@learnwise.com",
        "password": "CorrectPassword123!",
        "role": "learner",
    }
    reg_resp = client.post("/api/auth/register", json=payload)
    assert reg_resp.status_code == status.HTTP_201_CREATED

    bad_login = {
        "email": "charlie@learnwise.com",
        "password": "WrongPassword999!",
    }
    resp = client.post("/api/auth/login", json=bad_login)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid email or password" in resp.json()["detail"].lower()


def test_instructor_registration_requires_invite_code(client, monkeypatch):
    """Instructor registration returns 403 unless valid INSTRUCTOR_INVITE_CODE is provided."""
    monkeypatch.setenv("INSTRUCTOR_INVITE_CODE", "test_secret_invite_2026")

    # 1. No invite code -> 403
    no_code_payload = {
        "name": "Prof Smith",
        "email": "prof.smith@learnwise.com",
        "password": "ProfPassword123!",
        "role": "instructor",
    }
    resp_no_code = client.post("/api/auth/register", json=no_code_payload)
    assert resp_no_code.status_code == status.HTTP_403_FORBIDDEN
    assert "invite code" in resp_no_code.json()["detail"].lower()

    # 2. Wrong invite code -> 403
    wrong_code_payload = {
        **no_code_payload,
        "invite_code": "wrong_invite_code",
    }
    resp_wrong_code = client.post("/api/auth/register", json=wrong_code_payload)
    assert resp_wrong_code.status_code == status.HTTP_403_FORBIDDEN

    # 3. Correct invite code -> 201 Created
    correct_code_payload = {
        **no_code_payload,
        "invite_code": "test_secret_invite_2026",
    }
    resp_ok = client.post("/api/auth/register", json=correct_code_payload)
    assert resp_ok.status_code == status.HTTP_201_CREATED
    assert resp_ok.json()["role"] == "instructor"
    assert "created_at" in resp_ok.json()
