"""Prova, no nível HTTP, que o rate limiting distribuído (Postgres)
está de fato aplicado nos endpoints pedidos: login, registro,
verificação de e-mail, upload de vídeo e endpoints que chamam a
OpenAI.

A lógica pura do algoritmo (janela fixa, reset, contadores
independentes) já é coberta em tests/unit/test_rate_limit_service.py e
não é duplicada aqui. Usamos os limites reais importados de
app.rate_limit.service (em vez de números fixos) para que estes testes
não fiquem desatualizados se os defaults mudarem.
"""

import pytest

from app.rate_limit import service as rate_limit_service
from tests import factories

pytestmark = pytest.mark.security


VALID_PASSWORD = "Senha123!"


# --- login: por IP ---


async def test_login_is_rate_limited_per_ip(client, db_session):
    user = factories.create_user(db_session, password=VALID_PASSWORD)
    payload = {"username": user.username, "password": "WrongPassword!"}

    for _ in range(rate_limit_service.LOGIN_MAX):
        response = await client.post("/users/login/", json=payload)
        assert response.status_code == 401

    blocked_response = await client.post("/users/login/", json=payload)
    assert blocked_response.status_code == 429
    assert "Retry-After" in blocked_response.headers


async def test_login_rate_limit_is_independent_per_ip(client, db_session):
    user = factories.create_user(db_session, password=VALID_PASSWORD)
    payload = {"username": user.username, "password": "WrongPassword!"}

    client.headers["X-Forwarded-For"] = "10.0.0.1"
    for _ in range(rate_limit_service.LOGIN_MAX):
        response = await client.post("/users/login/", json=payload)
        assert response.status_code == 401

    blocked_response = await client.post("/users/login/", json=payload)
    assert blocked_response.status_code == 429

    # Outro IP tem seu próprio orçamento, mesmo mirando o mesmo usuário.
    client.headers["X-Forwarded-For"] = "10.0.0.2"
    other_ip_response = await client.post("/users/login/", json=payload)
    assert other_ip_response.status_code == 401


# --- registro: por IP ---


async def test_register_is_rate_limited_per_ip(client):
    for _ in range(rate_limit_service.REGISTER_MAX):
        payload = {
            "username": f"user_{factories.unique_suffix()}",
            "email": f"{factories.unique_suffix()}@example.com",
            "password": VALID_PASSWORD,
        }
        response = await client.post("/users/register", json=payload)
        assert response.status_code == 201

    blocked_payload = {
        "username": f"user_{factories.unique_suffix()}",
        "email": f"{factories.unique_suffix()}@example.com",
        "password": VALID_PASSWORD,
    }
    blocked_response = await client.post(
        "/users/register", json=blocked_payload
    )
    assert blocked_response.status_code == 429


# --- verificação de e-mail: por IP ---


async def test_verify_email_is_rate_limited_per_ip(client):
    payload = {"email": "does-not-exist@example.com", "code": "000000"}

    for _ in range(rate_limit_service.VERIFY_EMAIL_MAX):
        response = await client.post("/users/verify-email", json=payload)
        assert response.status_code == 404

    blocked_response = await client.post(
        "/users/verify-email", json=payload
    )
    assert blocked_response.status_code == 429


async def test_resend_verification_is_rate_limited_per_ip(client):
    payload = {"email": "does-not-exist@example.com"}

    for _ in range(rate_limit_service.RESEND_VERIFICATION_MAX):
        response = await client.post(
            "/users/resend-verification", json=payload
        )
        assert response.status_code == 200

    blocked_response = await client.post(
        "/users/resend-verification", json=payload
    )
    assert blocked_response.status_code == 429


# --- upload de vídeo: por usuário autenticado ---


async def test_video_upload_is_rate_limited_per_user(
    authenticated_client,
):
    files = {"file": ("clip.mp4", b"fake video bytes", "video/mp4")}
    data = {"title": "Minha entrevista"}

    for _ in range(rate_limit_service.VIDEO_UPLOAD_MAX):
        response = await authenticated_client.post(
            "/videos/", data=data, files=files
        )
        assert response.status_code == 201

    blocked_response = await authenticated_client.post(
        "/videos/", data=data, files=files
    )
    assert blocked_response.status_code == 429


async def test_video_upload_rate_limit_is_independent_per_user(
    authenticated_client, authenticated_client_b
):
    files = {"file": ("clip.mp4", b"fake video bytes", "video/mp4")}
    data = {"title": "Minha entrevista"}

    for _ in range(rate_limit_service.VIDEO_UPLOAD_MAX):
        response = await authenticated_client.post(
            "/videos/", data=data, files=files
        )
        assert response.status_code == 201

    blocked_response = await authenticated_client.post(
        "/videos/", data=data, files=files
    )
    assert blocked_response.status_code == 429

    # Usuário B tem seu próprio orçamento, independente do usuário A.
    other_user_response = await authenticated_client_b.post(
        "/videos/", data=data, files=files
    )
    assert other_user_response.status_code == 201


# --- endpoints que chamam a OpenAI: por IP ---
#
# Usamos job_title vazio de propósito: o rate limiter roda como
# dependency ANTES da validação do corpo da rota, então a requisição
# já é contada mesmo que o handler rejeite com 422 antes de qualquer
# chamada à OpenAI. Isso prova que o limite protege o endpoint sem
# precisar mockar o client da OpenAI aqui (unit tests de mocking da
# OpenAI ficam na Fase 2, com o endpoint testado de ponta a ponta).


async def test_simulation_questions_openai_endpoint_is_rate_limited(
    client,
):
    payload = {"job_title": "", "seniority": "Pleno"}

    for _ in range(rate_limit_service.OPENAI_ENDPOINT_MAX):
        response = await client.post(
            "/interview-simulation/questions", json=payload
        )
        assert response.status_code == 422

    blocked_response = await client.post(
        "/interview-simulation/questions", json=payload
    )
    assert blocked_response.status_code == 429


async def test_generate_interview_questions_endpoint_is_rate_limited(
    client,
):
    data = {"job_title": "", "seniority": "Pleno"}

    for _ in range(rate_limit_service.OPENAI_ENDPOINT_MAX):
        response = await client.post(
            "/generate-interview-questions/", data=data
        )
        assert response.status_code == 422

    blocked_response = await client.post(
        "/generate-interview-questions/", data=data
    )
    assert blocked_response.status_code == 429


async def test_openai_endpoint_rate_limit_is_independent_per_scope(
    client,
):
    # Esgotar o orçamento de "openai-simulation-questions" não afeta
    # o orçamento (mesmo limite, chave de escopo diferente) de
    # "openai-generate-questions".
    payload = {"job_title": "", "seniority": "Pleno"}
    for _ in range(rate_limit_service.OPENAI_ENDPOINT_MAX):
        response = await client.post(
            "/interview-simulation/questions", json=payload
        )
        assert response.status_code == 422

    blocked_response = await client.post(
        "/interview-simulation/questions", json=payload
    )
    assert blocked_response.status_code == 429

    other_scope_response = await client.post(
        "/generate-interview-questions/",
        data={"job_title": "", "seniority": "Pleno"},
    )
    assert other_scope_response.status_code == 422
