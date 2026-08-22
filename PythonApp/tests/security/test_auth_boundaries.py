import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.refresh_token_service import hash_refresh_token
from app.auth.token_service import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)
from tests import factories

pytestmark = pytest.mark.security


# --- get_current_user boundaries ---


async def test_protected_route_without_token_returns_401(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_protected_route_with_malformed_token_returns_401(client):
    client.headers.update({"Authorization": "Bearer not-a-jwt"})
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_protected_route_with_expired_token_returns_401(client):
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now - timedelta(minutes=120),
            "exp": now - timedelta(minutes=60),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    client.headers.update({"Authorization": f"Bearer {expired_token}"})
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_protected_route_with_token_missing_sub_returns_401(client):
    now = datetime.now(timezone.utc)
    token_without_sub = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=60)},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    client.headers.update({"Authorization": f"Bearer {token_without_sub}"})
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_protected_route_with_unknown_user_id_returns_401(client):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    client.headers.update({"Authorization": f"Bearer {token}"})
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_protected_route_with_token_signed_by_wrong_key_returns_401(
    client,
):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "a-completely-different-secret-key",
        algorithm=JWT_ALGORITHM,
    )

    client.headers.update({"Authorization": f"Bearer {token}"})
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_inactive_user_is_rejected(client, db_session):
    inactive_user = factories.create_user(db_session, is_active=False)
    from app.auth.token_service import create_access_token

    token = create_access_token(inactive_user.id)
    client.headers.update({"Authorization": f"Bearer {token}"})

    response = await client.get("/users/me")
    assert response.status_code == 403


async def test_unverified_user_is_rejected(client, db_session):
    unverified_user = factories.create_user(
        db_session, is_email_verified=False
    )
    from app.auth.token_service import create_access_token

    token = create_access_token(unverified_user.id)
    client.headers.update({"Authorization": f"Bearer {token}"})

    response = await client.get("/users/me")
    assert response.status_code == 403


# --- refresh token rotation / reuse detection ---


async def test_refresh_token_rotates_on_use(client, db_session, user):
    raw_token = factories_create_raw_refresh_token(db_session, user)

    response = await client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refresh_token"] != raw_token


async def test_reused_refresh_token_revokes_entire_family(
    client, db_session, user
):
    raw_token = factories_create_raw_refresh_token(db_session, user)

    first_response = await client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert first_response.status_code == 200
    rotated_token = first_response.json()["refresh_token"]

    reuse_response = await client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert reuse_response.status_code == 401

    blocked_response = await client.post(
        "/users/refresh", json={"refresh_token": rotated_token}
    )
    assert blocked_response.status_code == 401


async def test_expired_refresh_token_is_rejected(client, db_session, user):
    raw_token = "expired-raw-refresh-token"
    factories.create_refresh_token_row(
        db_session,
        user,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    response = await client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert response.status_code == 401


async def test_unknown_refresh_token_is_rejected(client):
    response = await client.post(
        "/users/refresh", json={"refresh_token": "totally-unknown-token"}
    )
    assert response.status_code == 401


async def test_refresh_token_of_user_a_does_not_authenticate_as_user_b(
    client, db_session, user, second_user
):
    raw_token = factories_create_raw_refresh_token(db_session, user)

    response = await client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert response.status_code == 200

    new_access_token = response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {new_access_token}"})

    me_response = await client.get("/users/me")
    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(user.id)
    assert me_response.json()["id"] != str(second_user.id)


# --- password change revokes refresh tokens ---


async def test_password_change_revokes_existing_refresh_tokens(
    authenticated_client, db_session, user
):
    raw_token = factories_create_raw_refresh_token(db_session, user)

    response = await authenticated_client.put(
        "/users/me/password",
        json={
            "current_password": "Senha123!",
            "new_password": "NovaSenhaForte123!",
        },
    )
    assert response.status_code == 200

    refresh_response = await authenticated_client.post(
        "/users/refresh", json={"refresh_token": raw_token}
    )
    assert refresh_response.status_code == 401


async def test_password_change_requires_correct_current_password(
    authenticated_client,
):
    response = await authenticated_client.put(
        "/users/me/password",
        json={
            "current_password": "WrongPassword!",
            "new_password": "NovaSenhaForte123!",
        },
    )
    assert response.status_code == 401


def factories_create_raw_refresh_token(db_session, user):
    from app.auth.refresh_token_service import create_refresh_token

    raw_token = create_refresh_token(db=db_session, user_id=user.id)
    db_session.commit()
    return raw_token
