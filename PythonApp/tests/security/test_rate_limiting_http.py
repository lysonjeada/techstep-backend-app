"""Prova, no nível HTTP, que o rate limiting distribuído (Postgres)
está de fato aplicado nos endpoints pedidos: login, registro,
verificação de e-mail, upload de vídeo e endpoints que chamam a
OpenAI.

A lógica pura do algoritmo (janela fixa, reset, contadores
independentes) já é coberta em tests/unit/test_rate_limit_service.py e
não é duplicada aqui. Usamos os limites reais importados de
app.rate_limit.service/app.credits.config (em vez de números fixos)
para que estes testes não fiquem desatualizados se os defaults
mudarem.

Os endpoints que chamam a OpenAI agora exigem autenticação e são
protegidos por app.credits.service.ai_credit_gate (que estende esse
mesmo rate limiter — dentro do limite gratuito por usuário, o
comportamento é idêntico ao rate limiter puro testado aqui; o que
acontece depois do limite gratuito estourar, incluindo débito de
créditos e reembolso, é coberto em
tests/integration/test_ai_credit_gate.py).
"""

import pytest

from app.credits.config import AI_CREDIT_FREE_LIMIT
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


# --- endpoints que chamam a OpenAI: autenticados, por usuário ---
#
# Usamos job_title vazio de propósito: o gate de créditos (que
# encapsula o mesmo rate limiter) roda como dependency ANTES da
# validação do corpo da rota, então a requisição já é contada mesmo
# que o handler rejeite com 422 antes de qualquer chamada à OpenAI.
# Isso prova que o limite gratuito protege o endpoint sem precisar
# mockar o client da OpenAI aqui. Ficam sem saldo comprado (balance=0)
# de propósito: dentro do limite gratuito por usuário
# (AI_CREDIT_FREE_LIMIT), nenhuma requisição toca no saldo.


async def test_simulation_questions_openai_endpoint_is_rate_limited(
    authenticated_client,
):
    payload = {"job_title": "", "seniority": "Pleno"}

    for _ in range(AI_CREDIT_FREE_LIMIT):
        response = await authenticated_client.post(
            "/interview-simulation/questions", json=payload
        )
        assert response.status_code == 422

    blocked_response = await authenticated_client.post(
        "/interview-simulation/questions", json=payload
    )
    assert blocked_response.status_code == 402
    assert (
        blocked_response.json()["detail"]["code"]
        == "INSUFFICIENT_AI_CREDITS"
    )


async def test_generate_interview_questions_endpoint_is_rate_limited(
    authenticated_client,
):
    data = {"job_title": "", "seniority": "Pleno"}

    for _ in range(AI_CREDIT_FREE_LIMIT):
        response = await authenticated_client.post(
            "/generate-interview-questions/", data=data
        )
        assert response.status_code == 422

    blocked_response = await authenticated_client.post(
        "/generate-interview-questions/", data=data
    )
    assert blocked_response.status_code == 402


async def test_openai_endpoint_free_limit_requires_authentication(
    client,
):
    response = await client.post(
        "/interview-simulation/questions",
        json={"job_title": "Dev", "seniority": "Pleno"},
    )

    assert response.status_code == 401


async def test_openai_endpoint_free_limit_is_independent_per_scope(
    authenticated_client,
):
    # Esgotar o orçamento gratuito de "simulation_questions" não afeta
    # o orçamento (mesmo limite, escopo diferente) de
    # "generate_questions".
    payload = {"job_title": "", "seniority": "Pleno"}

    for _ in range(AI_CREDIT_FREE_LIMIT):
        response = await authenticated_client.post(
            "/interview-simulation/questions", json=payload
        )
        assert response.status_code == 422

    blocked_response = await authenticated_client.post(
        "/interview-simulation/questions", json=payload
    )
    assert blocked_response.status_code == 402

    other_scope_response = await authenticated_client.post(
        "/generate-interview-questions/",
        data={"job_title": "", "seniority": "Pleno"},
    )
    assert other_scope_response.status_code == 422


async def test_openai_endpoint_free_limit_is_independent_per_user(
    authenticated_client, authenticated_client_b
):
    payload = {"job_title": "", "seniority": "Pleno"}

    for _ in range(AI_CREDIT_FREE_LIMIT):
        response = await authenticated_client.post(
            "/interview-simulation/questions", json=payload
        )
        assert response.status_code == 422

    blocked_response = await authenticated_client.post(
        "/interview-simulation/questions", json=payload
    )
    assert blocked_response.status_code == 402

    # Usuário B tem seu próprio orçamento gratuito, independente de A.
    other_user_response = await authenticated_client_b.post(
        "/interview-simulation/questions", json=payload
    )
    assert other_user_response.status_code == 422
