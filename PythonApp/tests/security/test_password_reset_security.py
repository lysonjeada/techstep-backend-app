import logging

import pytest

from tests import factories

pytestmark = pytest.mark.security


NEW_PASSWORD = "NovaSenhaForte456!"


@pytest.fixture()
def capture_techstep_logs(caplog, monkeypatch):
    techstep_logger = logging.getLogger("techstep")
    monkeypatch.setattr(techstep_logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="techstep")
    return caplog


async def _get_reset_token(client, user, mock_emails):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = mock_emails[-1]["code"]

    verify_response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )
    return verify_response.json()["reset_token"]


# --- ENUMERAÇÃO DE E-MAIL ---


async def test_forgot_password_same_status_and_shape_regardless_of_email(
    client, user, _mock_password_reset_email
):
    existing_response = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )
    missing_response = await client.post(
        "/users/forgot-password",
        json={"email": "definitivamente-nao-existe@example.com"},
    )

    assert existing_response.status_code == missing_response.status_code
    assert (
        existing_response.json().keys()
        == missing_response.json().keys()
    )
    assert (
        existing_response.json()["message"]
        == missing_response.json()["message"]
    )


async def test_forgot_password_cooldown_never_surfaces_as_different_status(
    client, user, _mock_password_reset_email
):
    """Um 429 aqui só poderia acontecer para e-mails cadastrados (o
    cooldown só é checado depois de encontrar o usuário) — se
    vazasse, um atacante distinguiria e-mails reais de inexistentes
    batendo o endpoint duas vezes seguidas."""

    first = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )
    second = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )

    assert first.status_code == 200
    assert second.status_code == 200


# --- VAZAMENTO EM LOGS ---


async def test_forgot_password_never_logs_the_code(
    client, user, _mock_password_reset_email, capture_techstep_logs
):
    await client.post("/users/forgot-password", json={"email": user.email})

    code = _mock_password_reset_email[0]["code"]

    assert code not in capture_techstep_logs.text


async def test_verify_reset_code_never_logs_the_code(
    client, user, _mock_password_reset_email, capture_techstep_logs
):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = _mock_password_reset_email[0]["code"]

    await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )

    assert code not in capture_techstep_logs.text


async def test_verify_reset_code_never_logs_the_reset_token(
    client, user, _mock_password_reset_email, capture_techstep_logs
):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = _mock_password_reset_email[0]["code"]

    response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )
    reset_token = response.json()["reset_token"]

    assert reset_token not in capture_techstep_logs.text


async def test_reset_password_never_logs_new_password_or_token(
    client, user, db_session, _mock_password_reset_email,
    capture_techstep_logs,
):
    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    db_session.refresh(user)

    log_text = capture_techstep_logs.text
    assert NEW_PASSWORD not in log_text
    assert reset_token not in log_text
    assert user.hashed_password not in log_text


async def test_reset_password_revoked_refresh_token_never_logged(
    client, user, db_session, _mock_password_reset_email,
    capture_techstep_logs,
):
    from app.auth.refresh_token_service import create_refresh_token

    old_refresh_token = create_refresh_token(db_session, user.id)
    db_session.commit()

    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    assert old_refresh_token not in capture_techstep_logs.text


# --- IDOR / CROSS-USER ---


async def test_reset_token_is_scoped_to_the_user_who_requested_it(
    client, user, second_user, _mock_password_reset_email
):
    """Mesmo que alguém descubra o reset_token de outra pessoa, ele só
    pode redefinir a senha da conta original — não existe forma de
    direcioná-lo a outro user_id via payload, já que o token não
    carrega nenhum identificador manipulável pelo cliente."""

    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    second_user_login_with_new_password = await client.post(
        "/users/login/",
        json={
            "username": second_user.username,
            "password": NEW_PASSWORD,
        },
    )
    assert second_user_login_with_new_password.status_code == 401

    original_user_login = await client.post(
        "/users/login/",
        json={"username": user.username, "password": NEW_PASSWORD},
    )
    assert original_user_login.status_code == 200


# --- MASS ASSIGNMENT ---


async def test_reset_password_payload_cannot_set_arbitrary_user_fields(
    client, user, _mock_password_reset_email
):
    """ResetPasswordRequest só aceita reset_token e new_password —
    campos extras no payload (ex.: is_active, is_email_verified,
    username) precisam ser ignorados pelo Pydantic, não aplicados ao
    usuário."""

    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
            "is_active": False,
            "is_email_verified": False,
            "username": "conta-sequestrada",
        },
    )

    assert response.status_code == 200

    login_response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": NEW_PASSWORD},
    )
    assert login_response.status_code == 200


# --- 500 SANITIZADO ---


async def test_reset_password_unexpected_failure_returns_sanitized_500(
    client, user, _mock_password_reset_email, monkeypatch
):
    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    import app.auth.router as auth_router_module

    def _boom(*args, **kwargs):
        raise RuntimeError("db connection lost: internal detail")

    monkeypatch.setattr(
        auth_router_module,
        "revoke_all_refresh_tokens_for_user",
        _boom,
    )

    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 500
    body = response.json()
    assert "db connection lost" not in str(body)
    assert "internal detail" not in str(body)
    assert "RuntimeError" not in str(body)


async def test_reset_password_rolls_back_on_failure(
    client, user, db_session, _mock_password_reset_email, monkeypatch
):
    """Se a revogação de refresh tokens falhar depois da senha já ter
    sido trocada em memória, nada pode ser persistido — a senha antiga
    continua valendo."""

    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    import app.auth.router as auth_router_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        auth_router_module,
        "revoke_all_refresh_tokens_for_user",
        _boom,
    )

    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 500

    old_password_login = await client.post(
        "/users/login/",
        json={"username": user.username, "password": "Senha123!"},
    )
    assert old_password_login.status_code == 200
