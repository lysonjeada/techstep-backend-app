"""Testes de integração dos endpoints GET /ai-credits/balance e
POST /ai-credits/apple/purchases contra a aplicação real (app.main).

Mocka apenas a verificação de assinatura Apple
(app.credits.router.verify_signed_transaction) — nenhum teste desta
suíte faz uma chamada real à Apple. O algoritmo de verificação em si é
coberto em tests/unit/test_apple_verification.py.
"""

from types import SimpleNamespace

import pytest
from appstoreserverlibrary.models.Environment import Environment

import app.credits.router as credits_router_module
from app.credits.apple_verification import ApplePurchaseVerificationError
from app.credits.config import AI_CREDIT_PRODUCTS
from app.credits.service import credit, get_balance

pytestmark = pytest.mark.integration


def _fake_decoded_transaction(
    *,
    product_id="lys.com.career-app.credits.10",
    transaction_id="apple-txn-1",
    original_transaction_id=None,
    environment=Environment.SANDBOX,
):
    return SimpleNamespace(
        product_id=product_id,
        transaction_id=transaction_id,
        original_transaction_id=(
            original_transaction_id or transaction_id
        ),
        environment=environment,
        raw_environment=environment.value if environment else None,
    )


def _mock_verification(monkeypatch, decoded_transaction=None, *, error=None):
    def _fake_verify(signed_transaction):
        if error is not None:
            raise error

        return decoded_transaction or _fake_decoded_transaction()

    monkeypatch.setattr(
        credits_router_module,
        "verify_signed_transaction",
        _fake_verify,
    )


# --- balance ---


async def test_balance_requires_authentication(client):
    response = await client.get("/ai-credits/balance")

    assert response.status_code == 401


async def test_authenticated_user_sees_own_balance_starting_at_zero(
    authenticated_client,
):
    response = await authenticated_client.get("/ai-credits/balance")

    assert response.status_code == 200
    assert response.json() == {"balance": 0}


async def test_user_never_sees_another_users_balance(
    authenticated_client,
    authenticated_client_b,
    db_session,
    second_user,
):
    credit(db_session, second_user.id, 42)

    response_a = await authenticated_client.get("/ai-credits/balance")
    assert response_a.json() == {"balance": 0}

    response_b = await authenticated_client_b.get("/ai-credits/balance")
    assert response_b.json() == {"balance": 42}


# --- apple purchases ---


async def test_purchase_requires_authentication(client, monkeypatch):
    _mock_verification(monkeypatch)

    response = await client.post(
        "/ai-credits/apple/purchases",
        json={"signed_transaction": "fake-jws", "product_id": "x"},
    )

    assert response.status_code == 401


async def test_valid_purchase_grants_the_configured_credits(
    authenticated_client, monkeypatch, db_session, user
):
    product_id = "lys.com.career-app.credits.30"

    _mock_verification(
        monkeypatch,
        _fake_decoded_transaction(
            product_id=product_id,
            transaction_id="txn-valid-1",
        ),
    )

    response = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "fake-jws",
            "product_id": product_id,
        },
    )

    assert response.status_code == 200

    body = response.json()
    expected_credits = AI_CREDIT_PRODUCTS[product_id]

    assert body["credits_added"] == expected_credits
    assert body["balance"] == expected_credits
    assert body["already_processed"] is False
    assert get_balance(db_session, user.id) == expected_credits


async def test_duplicate_transaction_does_not_grant_credits_twice(
    authenticated_client, monkeypatch, db_session, user
):
    product_id = "lys.com.career-app.credits.10"

    _mock_verification(
        monkeypatch,
        _fake_decoded_transaction(
            product_id=product_id,
            transaction_id="txn-dup-http",
        ),
    )

    first = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "fake-jws",
            "product_id": product_id,
        },
    )
    assert first.status_code == 200
    assert first.json()["already_processed"] is False

    second = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "fake-jws",
            "product_id": product_id,
        },
    )
    assert second.status_code == 200
    assert second.json()["already_processed"] is True
    assert second.json()["credits_added"] == 0

    assert (
        get_balance(db_session, user.id)
        == AI_CREDIT_PRODUCTS[product_id]
    )


async def test_unknown_product_is_rejected(
    authenticated_client, monkeypatch, db_session, user
):
    _mock_verification(
        monkeypatch,
        _fake_decoded_transaction(
            product_id="not.a.real.product",
            transaction_id="txn-unknown",
        ),
    )

    response = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "fake-jws",
            "product_id": "not.a.real.product",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNKNOWN_PRODUCT"
    assert get_balance(db_session, user.id) == 0


async def test_invalid_apple_signature_is_rejected(
    authenticated_client, monkeypatch
):
    _mock_verification(
        monkeypatch,
        error=ApplePurchaseVerificationError("assinatura inválida"),
    )

    response = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "not-a-real-jws",
            "product_id": "whatever",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]["code"]
        == "INVALID_APPLE_TRANSACTION"
    )


async def test_client_sent_product_id_is_ignored_in_favor_of_the_verified_one(
    authenticated_client, monkeypatch, db_session, user
):
    real_product_id = "lys.com.career-app.credits.100"

    _mock_verification(
        monkeypatch,
        _fake_decoded_transaction(
            product_id=real_product_id,
            transaction_id="txn-spoof-attempt",
        ),
    )

    # O cliente manda um product_id diferente do que a Apple realmente
    # assinou (tentando implicitamente manipular a quantidade
    # concedida) — o backend deve ignorar isso e usar só o payload
    # verificado.
    response = await authenticated_client.post(
        "/ai-credits/apple/purchases",
        json={
            "signed_transaction": "fake-jws",
            "product_id": "lys.com.career-app.credits.10",
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["credits_added"]
        == AI_CREDIT_PRODUCTS[real_product_id]
    )
    assert (
        get_balance(db_session, user.id)
        == AI_CREDIT_PRODUCTS[real_product_id]
    )
