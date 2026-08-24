"""Fluxo HTTP real de autenticação: registro, login, /users/me.

Os testes unitários de token/refresh já cobrem a lógica pura em
tests/unit/. Os testes de boundary/IDOR já cobrem token inválido,
expirado, adulterado, rotação de refresh e ownership em
tests/security/. Aqui o foco é o comportamento do endpoint HTTP em si:
shape da resposta, regras de negócio do registro/login e que nenhum
campo administrativo/sensível vaze ou possa ser setado pelo cliente.
"""

import pytest

from app.auth.security import verify_password
from tests import factories

pytestmark = pytest.mark.integration


VALID_PASSWORD = "SenhaForte123!"


def _register_payload(**overrides):
    suffix = factories.unique_suffix()
    payload = {
        "username": f"novo_user_{suffix}",
        "email": f"novo-{suffix}@example.com",
        "password": VALID_PASSWORD,
    }
    payload.update(overrides)
    return payload


# --- REGISTRO ---


async def test_register_with_valid_data_returns_201(client):
    response = await client.post(
        "/users/register", json=_register_payload()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["verification_required"] is True
    assert "user_id" in body
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_persists_hashed_password_only(client, db_session):
    payload = _register_payload()

    response = await client.post("/users/register", json=payload)
    assert response.status_code == 201

    from app import models

    stored = (
        db_session.query(models.User)
        .filter(models.User.email == payload["email"].lower())
        .first()
    )
    assert stored is not None
    assert stored.hashed_password != payload["password"]
    assert verify_password(payload["password"], stored.hashed_password)


async def test_register_new_user_is_not_verified_yet(client, db_session):
    payload = _register_payload()

    response = await client.post("/users/register", json=payload)
    assert response.status_code == 201

    from app import models

    stored = (
        db_session.query(models.User)
        .filter(models.User.email == payload["email"].lower())
        .first()
    )
    assert stored.is_email_verified is False


async def test_register_duplicate_verified_email_returns_409(
    client, db_session
):
    existing = factories.create_user(db_session, is_email_verified=True)

    response = await client.post(
        "/users/register",
        json=_register_payload(email=existing.email),
    )

    assert response.status_code == 409


async def test_register_duplicate_username_returns_409(client, db_session):
    existing = factories.create_user(db_session, is_email_verified=True)

    response = await client.post(
        "/users/register",
        json=_register_payload(username=existing.username),
    )

    assert response.status_code == 409


async def test_register_duplicate_pending_email_resends_code(
    client, db_session
):
    pending = factories.create_user(db_session, is_email_verified=False)

    response = await client.post(
        "/users/register",
        json=_register_payload(email=pending.email),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["verification_required"] is True
    assert body["user_id"] == str(pending.id)


async def test_register_invalid_email_returns_422(client):
    response = await client.post(
        "/users/register",
        json=_register_payload(email="not-an-email"),
    )

    assert response.status_code == 422


@pytest.mark.parametrize("bad_password", ["short1", "1234567"])
async def test_register_password_below_minimum_length_returns_422(
    client, bad_password
):
    response = await client.post(
        "/users/register",
        json=_register_payload(password=bad_password),
    )

    assert response.status_code == 422


async def test_register_ignores_client_supplied_admin_fields(
    client, db_session
):
    payload = _register_payload()
    payload["is_active"] = False
    payload["is_email_verified"] = True
    payload["hashed_password"] = "hacked-hash"
    payload["id"] = "00000000-0000-0000-0000-000000000000"

    response = await client.post("/users/register", json=payload)
    assert response.status_code == 201

    from app import models

    stored = (
        db_session.query(models.User)
        .filter(models.User.email == payload["email"].lower())
        .first()
    )
    assert stored.is_active is True
    assert stored.is_email_verified is False
    assert stored.hashed_password != "hacked-hash"
    assert str(stored.id) != payload["id"]


# --- LOGIN ---


async def test_login_with_valid_credentials_returns_tokens(
    client, db_session
):
    user = factories.create_user(db_session, password=VALID_PASSWORD)

    response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": VALID_PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["id"] == str(user.id)
    assert "hashed_password" not in body
    assert "password" not in body


async def test_login_with_email_as_identifier_succeeds(client, db_session):
    user = factories.create_user(db_session, password=VALID_PASSWORD)

    response = await client.post(
        "/users/login/",
        json={"username": user.email, "password": VALID_PASSWORD},
    )

    assert response.status_code == 200


async def test_login_with_wrong_password_returns_401(client, db_session):
    user = factories.create_user(db_session, password=VALID_PASSWORD)

    response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": "WrongPassword!"},
    )

    assert response.status_code == 401
    assert "hashed_password" not in response.text


async def test_login_with_nonexistent_user_returns_401(client):
    response = await client.post(
        "/users/login/",
        json={"username": "does-not-exist", "password": "whatever123"},
    )

    assert response.status_code == 401


async def test_login_with_unverified_email_returns_403(client, db_session):
    user = factories.create_user(
        db_session, password=VALID_PASSWORD, is_email_verified=False
    )

    response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": VALID_PASSWORD},
    )

    assert response.status_code == 403


async def test_login_creates_refresh_token_row_in_db(client, db_session):
    from app.auth.models import RefreshToken

    user = factories.create_user(db_session, password=VALID_PASSWORD)

    response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": VALID_PASSWORD},
    )
    assert response.status_code == 200

    raw_refresh_token = response.json()["refresh_token"]

    rows = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id)
        .all()
    )
    assert len(rows) == 1
    # o valor bruto do refresh token nunca deve estar salvo no banco.
    assert rows[0].token_hash != raw_refresh_token


# --- /users/me ---


async def test_get_me_without_token_returns_401(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_get_me_with_valid_token_returns_own_profile(
    authenticated_client, user
):
    response = await authenticated_client.get("/users/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert "hashed_password" not in body
    assert "password" not in body


async def test_update_me_changes_only_allowed_fields(
    authenticated_client, user
):
    new_username = f"updated_{factories.unique_suffix()}"

    response = await authenticated_client.put(
        "/users/me", json={"username": new_username}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == new_username
    assert body["email"] == user.email


async def test_update_me_ignores_admin_fields_in_payload(
    authenticated_client, user, db_session
):
    response = await authenticated_client.put(
        "/users/me",
        json={
            "is_active": False,
            "is_email_verified": False,
            "hashed_password": "hacked-hash",
        },
    )

    assert response.status_code == 200

    db_session.expire_all()
    from app import models

    stored = db_session.query(models.User).filter(
        models.User.id == user.id
    ).first()
    assert stored.is_active is True
    assert stored.is_email_verified is True
    assert stored.hashed_password != "hacked-hash"


async def test_update_me_password_field_is_rejected(authenticated_client):
    response = await authenticated_client.put(
        "/users/me", json={"password": "NovaSenha123!"}
    )

    assert response.status_code == 422


async def test_update_me_to_existing_email_returns_409(
    authenticated_client, db_session, second_user
):
    response = await authenticated_client.put(
        "/users/me", json={"email": second_user.email}
    )

    assert response.status_code == 409


async def test_delete_me_removes_only_own_account(
    authenticated_client, user, db_session
):
    response = await authenticated_client.delete("/users/me")
    assert response.status_code == 204

    db_session.expire_all()
    from app import models

    stored = (
        db_session.query(models.User)
        .filter(models.User.id == user.id)
        .first()
    )
    assert stored is None


async def test_deleted_user_can_no_longer_login(
    authenticated_client, user, db_session
):
    delete_response = await authenticated_client.delete("/users/me")
    assert delete_response.status_code == 204

    login_response = await authenticated_client.post(
        "/users/login/",
        json={"username": user.username, "password": "Senha123!"},
    )
    assert login_response.status_code == 401
