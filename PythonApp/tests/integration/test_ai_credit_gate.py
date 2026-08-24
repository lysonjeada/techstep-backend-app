"""Testes de integração de app.credits.service.ai_credit_gate: o
comportamento HTTP completo da dependency (incluindo o reembolso
automático via yield-dependency quando o handler falha por um motivo
técnico), isolado dos endpoints reais de IA — usa um FastAPI mínimo de
teste em vez de app.main, para não precisar mockar a OpenAI aqui (isso
já é indiretamente coberto por tests/security/test_rate_limiting_http.py,
que exercita o gate plugado nos endpoints reais até o limite gratuito).
"""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.auth.token_service import create_access_token
from app.credits.service import ai_credit_gate, credit, get_balance
from app.database import get_db
from tests import factories

pytestmark = pytest.mark.integration


SCOPE = "test_ai_credit_gate_scope"
FREE_LIMIT = 2


def _build_test_app(db_session, *, behavior="success"):
    app = FastAPI()

    @app.post("/consume")
    async def consume(
        _gate=Depends(
            ai_credit_gate(
                SCOPE,
                cost=1,
                free_limit=FREE_LIMIT,
                window_seconds=3600,
            )
        ),
    ):
        if behavior == "technical_failure":
            # Equivalente ao que os routers reais fazem: um erro
            # inesperado (ex.: falha da OpenAI) vira HTTPException 500.
            raise HTTPException(status_code=500, detail="boom")

        if behavior == "user_caused_error":
            # Equivalente a uma regra de negócio rejeitada dentro do
            # handler (ex.: PDF corrompido) — 4xx, não gera reembolso.
            raise HTTPException(status_code=422, detail="bad input")

        return {"ok": True}

    app.dependency_overrides[get_db] = lambda: db_session

    return app


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _post_consume(app, user, times=1):
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=_auth_headers(user),
    ) as client:
        response = None

        for _ in range(times):
            response = await client.post("/consume")

        return response


async def test_requests_within_free_limit_never_touch_the_balance(
    db_session,
):
    user = factories.create_user(db_session)
    app = _build_test_app(db_session)

    response = await _post_consume(app, user, times=FREE_LIMIT)

    assert response.status_code == 200
    assert get_balance(db_session, user.id) == 0


async def test_request_beyond_free_limit_debits_a_credit_when_available(
    db_session,
):
    user = factories.create_user(db_session)
    credit(db_session, user.id, 5)
    app = _build_test_app(db_session)

    response = await _post_consume(app, user, times=FREE_LIMIT + 1)

    assert response.status_code == 200
    assert get_balance(db_session, user.id) == 4


async def test_request_beyond_free_limit_returns_402_when_balance_is_zero(
    db_session,
):
    user = factories.create_user(db_session)
    app = _build_test_app(db_session)

    response = await _post_consume(app, user, times=FREE_LIMIT + 1)

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "INSUFFICIENT_AI_CREDITS"


async def test_balance_exactly_equal_to_cost_is_consumed_then_blocks(
    db_session,
):
    user = factories.create_user(db_session)
    credit(db_session, user.id, 1)
    app = _build_test_app(db_session)

    ok_response = await _post_consume(app, user, times=FREE_LIMIT + 1)
    assert ok_response.status_code == 200
    assert get_balance(db_session, user.id) == 0

    blocked_response = await _post_consume(app, user, times=1)
    assert blocked_response.status_code == 402


async def test_technical_failure_refunds_the_debited_credit(db_session):
    user = factories.create_user(db_session)
    credit(db_session, user.id, 5)
    app = _build_test_app(db_session, behavior="technical_failure")

    response = await _post_consume(app, user, times=FREE_LIMIT + 1)

    assert response.status_code == 500
    # O crédito foi debitado (contagem passou do limite grátis) e
    # devolvido, porque a falha foi técnica (5xx), não do usuário.
    assert get_balance(db_session, user.id) == 5


async def test_user_caused_error_does_not_refund_the_debited_credit(
    db_session,
):
    user = factories.create_user(db_session)
    credit(db_session, user.id, 5)
    app = _build_test_app(db_session, behavior="user_caused_error")

    response = await _post_consume(app, user, times=FREE_LIMIT + 1)

    assert response.status_code == 422
    # Trade-off documentado: erro de validação de negócio descoberto
    # dentro do handler, depois do gate já ter debitado, NÃO devolve o
    # crédito.
    assert get_balance(db_session, user.id) == 4


async def test_gate_requires_authentication(db_session):
    app = _build_test_app(db_session)
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post("/consume")

    assert response.status_code == 401


async def test_free_limit_counter_is_independent_per_user(db_session):
    user_a = factories.create_user(db_session)
    user_b = factories.create_user(db_session)
    app = _build_test_app(db_session)

    response_a = await _post_consume(app, user_a, times=FREE_LIMIT)
    assert response_a.status_code == 200

    # Usuário B ainda não usou seu orçamento gratuito, independente de A.
    response_b = await _post_consume(app, user_b, times=1)
    assert response_b.status_code == 200
    assert get_balance(db_session, user_b.id) == 0
