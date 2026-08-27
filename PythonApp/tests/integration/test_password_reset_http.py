"""Fluxo HTTP completo de "esqueci minha senha": forgot-password,
verify-reset-code, reset-password.

Os testes de lógica pura (geração/validação de código, emissão e
consumo do reset token) já estão em
tests/unit/test_password_reset_service.py. Aqui o foco é o
comportamento do endpoint em si: forma da resposta, proteção contra
enumeração de e-mails, e o efeito ponta-a-ponta (senha antiga para de
funcionar, refresh tokens antigos são revogados).
"""

import pytest

from app.auth.security import verify_password
from tests import factories

pytestmark = pytest.mark.integration


GENERIC_FORGOT_PASSWORD_MESSAGE = (
    "Se o e-mail estiver cadastrado, enviaremos um código "
    "para redefinição da senha."
)


async def _run_full_flow(client, email):
    """Helper: dispara forgot-password, extrai o código enviado pelo
    mock de e-mail (via monkeypatch em conftest), verifica e devolve o
    reset_token."""

    forgot_response = await client.post(
        "/users/forgot-password", json={"email": email}
    )
    assert forgot_response.status_code == 200

    return forgot_response


# --- FORGOT PASSWORD ---


async def test_forgot_password_existing_email_returns_generic_message(
    client, user, _mock_password_reset_email
):
    response = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )

    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_FORGOT_PASSWORD_MESSAGE
    assert len(_mock_password_reset_email) == 1
    assert _mock_password_reset_email[0]["email"] == user.email


async def test_forgot_password_nonexistent_email_returns_same_message(
    client, _mock_password_reset_email
):
    response = await client.post(
        "/users/forgot-password",
        json={"email": "nao-existe@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_FORGOT_PASSWORD_MESSAGE
    assert len(_mock_password_reset_email) == 0


async def test_forgot_password_invalid_email_format_returns_422(client):
    response = await client.post(
        "/users/forgot-password", json={"email": "not-an-email"}
    )

    assert response.status_code == 422


async def test_forgot_password_normalizes_email_case_and_whitespace(
    client, db_session, _mock_password_reset_email
):
    # O endpoint de registro sempre normaliza (strip + lower) antes de
    # gravar — é assim que o e-mail chega no banco pra uma conta real.
    user = factories.create_user(
        db_session, email="mixed.case@example.com"
    )

    response = await client.post(
        "/users/forgot-password",
        json={"email": "  MIXED.CASE@EXAMPLE.COM  "},
    )

    assert response.status_code == 200
    assert len(_mock_password_reset_email) == 1
    assert _mock_password_reset_email[0]["email"] == user.email


async def test_forgot_password_creates_code_with_expiration(
    client, user, db_session, _mock_password_reset_email
):
    from app.auth.password_reset_service import get_latest_active_code

    await client.post("/users/forgot-password", json={"email": user.email})

    stored = get_latest_active_code(db_session, user.id)
    assert stored is not None
    assert stored.expires_at is not None


async def test_forgot_password_code_not_stored_as_plaintext(
    client, user, db_session, _mock_password_reset_email
):
    from app.auth.password_reset_service import get_latest_active_code

    await client.post("/users/forgot-password", json={"email": user.email})

    stored = get_latest_active_code(db_session, user.id)
    sent_code = _mock_password_reset_email[0]["code"]

    assert stored.code_hash != sent_code


async def test_forgot_password_second_request_within_cooldown_still_generic(
    client, user, _mock_password_reset_email
):
    """Uma segunda chamada dentro do cooldown não deve vazar um 429 —
    isso permitiria diferenciar e-mails cadastrados de inexistentes
    (que nunca acionam create_resend_code, logo nunca tomariam 429)."""

    first = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )
    second = await client.post(
        "/users/forgot-password", json={"email": user.email}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["message"] == GENERIC_FORGOT_PASSWORD_MESSAGE
    # Só o primeiro e-mail foi de fato enviado.
    assert len(_mock_password_reset_email) == 1


async def test_forgot_password_invalidates_previous_pending_request(
    client, user, db_session, _mock_password_reset_email
):
    from app.auth.password_reset_service import (
        get_latest_active_code,
        hash_reset_code,
    )

    await client.post("/users/forgot-password", json={"email": user.email})
    first_code = _mock_password_reset_email[0]["code"]

    # Libera o cooldown manualmente pra simular uma segunda solicitação
    # bem mais tarde.
    latest = get_latest_active_code(db_session, user.id)
    from datetime import datetime, timedelta, timezone

    latest.last_sent_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    await client.post("/users/forgot-password", json={"email": user.email})

    verify_response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": first_code},
    )

    assert verify_response.status_code == 400


# --- VERIFY RESET CODE ---


async def test_verify_reset_code_with_correct_code_returns_reset_token(
    client, user, _mock_password_reset_email
):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = _mock_password_reset_email[0]["code"]

    response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )

    assert response.status_code == 200
    body = response.json()
    assert "reset_token" in body
    assert isinstance(body["reset_token"], str)
    assert len(body["reset_token"]) > 20


async def test_verify_reset_code_with_wrong_code_returns_400(
    client, user, _mock_password_reset_email
):
    await client.post("/users/forgot-password", json={"email": user.email})

    response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": "000000"},
    )

    assert response.status_code == 400


async def test_verify_reset_code_nonexistent_email_returns_same_400(
    client,
):
    response = await client.post(
        "/users/verify-reset-code",
        json={"email": "nao-existe@example.com", "code": "123456"},
    )

    assert response.status_code == 400


async def test_verify_reset_code_wrong_format_returns_422(client, user):
    response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": "abc"},
    )

    assert response.status_code == 422


async def test_verify_reset_code_cannot_be_reused(
    client, user, _mock_password_reset_email
):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = _mock_password_reset_email[0]["code"]

    first = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )
    assert first.status_code == 200

    second = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )
    assert second.status_code == 400


# --- RESET PASSWORD ---


NEW_PASSWORD = "NovaSenhaForte456!"


async def _get_reset_token(client, user, mock_emails):
    await client.post("/users/forgot-password", json={"email": user.email})
    code = mock_emails[-1]["code"]

    verify_response = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": code},
    )
    return verify_response.json()["reset_token"]


async def test_reset_password_with_valid_token_returns_200(
    client, user, _mock_password_reset_email
):
    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 200


async def test_reset_password_with_invalid_token_returns_400(client):
    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": "invalid-token",
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 400


async def test_reset_password_stores_new_password_hashed_with_argon2(
    client, user, db_session, _mock_password_reset_email
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
    assert user.hashed_password != NEW_PASSWORD
    assert user.hashed_password.startswith("$argon2")
    assert verify_password(NEW_PASSWORD, user.hashed_password)


async def test_reset_password_old_password_no_longer_works(
    client, user, _mock_password_reset_email
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

    login_response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": "Senha123!"},
    )

    assert login_response.status_code == 401


async def test_reset_password_new_password_works_for_login(
    client, user, _mock_password_reset_email
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

    login_response = await client.post(
        "/users/login/",
        json={"username": user.username, "password": NEW_PASSWORD},
    )

    assert login_response.status_code == 200


async def test_reset_password_token_cannot_be_reused(
    client, user, _mock_password_reset_email
):
    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    first = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": NEW_PASSWORD,
        },
    )
    assert first.status_code == 200

    second = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": "OutraSenha789!",
        },
    )
    assert second.status_code == 400


async def test_reset_password_revokes_existing_refresh_tokens(
    client, user, db_session, _mock_password_reset_email
):
    from app.auth.refresh_token_service import create_refresh_token
    from app.auth.models import RefreshToken

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

    refresh_response = await client.post(
        "/users/refresh",
        json={"refresh_token": old_refresh_token},
    )

    assert refresh_response.status_code == 401

    db_session.refresh(user)
    stored_token = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id)
        .first()
    )
    assert stored_token.revoked_at is not None


async def test_reset_password_invalidates_other_active_reset_requests(
    client, user, db_session, _mock_password_reset_email
):
    """Um segundo fluxo de reset iniciado (mas não concluído) não pode
    ser usado depois que o primeiro já concluiu a troca de senha."""

    first_reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    from datetime import datetime, timedelta, timezone
    from app.auth.password_reset_service import get_latest_active_code

    latest = get_latest_active_code(db_session, user.id)
    if latest is not None:
        latest.last_sent_at = datetime.now(timezone.utc) - timedelta(
            hours=1
        )
        db_session.commit()

    await client.post("/users/forgot-password", json={"email": user.email})
    second_code = _mock_password_reset_email[-1]["code"]

    verify_second = await client.post(
        "/users/verify-reset-code",
        json={"email": user.email, "code": second_code},
    )
    second_reset_token = verify_second.json()["reset_token"]

    # Conclui com o token do primeiro fluxo.
    first_reset = await client.post(
        "/users/reset-password",
        json={
            "reset_token": first_reset_token,
            "new_password": NEW_PASSWORD,
        },
    )
    assert first_reset.status_code == 200

    # O token do segundo fluxo, ainda não usado, também deixa de valer.
    second_reset = await client.post(
        "/users/reset-password",
        json={
            "reset_token": second_reset_token,
            "new_password": "TerceiraSenha000!",
        },
    )
    assert second_reset.status_code == 400


async def test_reset_password_weak_password_returns_422(
    client, user, _mock_password_reset_email
):
    reset_token = await _get_reset_token(
        client, user, _mock_password_reset_email
    )

    response = await client.post(
        "/users/reset-password",
        json={
            "reset_token": reset_token,
            "new_password": "123",
        },
    )

    assert response.status_code == 422


async def test_reset_password_cannot_reset_another_users_password(
    client, user, second_user, _mock_password_reset_email
):
    """Token de reset do user A não pode redefinir a senha do user B —
    o token só carrega o próprio user_id internamente, não é
    influenciável pelo payload da requisição."""

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

    login_as_second_user_with_new_password = await client.post(
        "/users/login/",
        json={
            "username": second_user.username,
            "password": NEW_PASSWORD,
        },
    )

    assert login_as_second_user_with_new_password.status_code == 401
