import logging

import pytest

from tests import factories

pytestmark = pytest.mark.security


@pytest.fixture()
def capture_techstep_logs(caplog, monkeypatch):
    techstep_logger = logging.getLogger("techstep")
    monkeypatch.setattr(techstep_logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="techstep")
    return caplog


async def test_login_never_logs_password_or_tokens(
    client, db_session, capture_techstep_logs
):
    plain_password = "Senha123!"
    created_user = factories.create_user(
        db_session, password=plain_password
    )

    response = await client.post(
        "/users/login/",
        json={
            "username": created_user.username,
            "password": plain_password,
        },
    )
    assert response.status_code == 200

    body = response.json()
    access_token = body["access_token"]
    refresh_token = body["refresh_token"]

    log_text = capture_techstep_logs.text
    assert plain_password not in log_text
    assert access_token not in log_text
    assert refresh_token not in log_text


async def test_password_change_never_logs_passwords(
    authenticated_client, capture_techstep_logs
):
    response = await authenticated_client.put(
        "/users/me/password",
        json={
            "current_password": "Senha123!",
            "new_password": "OutraSenhaForte123!",
        },
    )
    assert response.status_code == 200

    log_text = capture_techstep_logs.text
    assert "Senha123!" not in log_text
    assert "OutraSenhaForte123!" not in log_text


async def test_authenticated_requests_never_log_bearer_token(
    authenticated_client, capture_techstep_logs
):
    bearer_token = authenticated_client.headers["Authorization"].split(
        " ", 1
    )[1]

    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200

    assert bearer_token not in capture_techstep_logs.text
