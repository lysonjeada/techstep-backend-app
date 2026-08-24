"""Testes unitários da lógica pura de saldo/débito/crédito de créditos
de IA (app.credits.service) — sem subir a aplicação inteira. O gate
plugado nos endpoints reais (incluindo reembolso automático) é coberto
em tests/integration/test_ai_credit_gate.py; os endpoints HTTP de
saldo/compra em tests/integration/test_credits_router.py.
"""

import pytest

from app.credits import service as credits_service
from tests import factories

pytestmark = pytest.mark.unit


def test_balance_starts_at_zero_for_a_new_user(db_session):
    user = factories.create_user(db_session)

    assert credits_service.get_balance(db_session, user.id) == 0


def test_ensure_balance_row_is_idempotent_and_does_not_reset_balance(
    db_session,
):
    user = factories.create_user(db_session)

    credits_service.ensure_balance_row(db_session, user.id)
    credits_service.credit(db_session, user.id, 5)
    credits_service.ensure_balance_row(db_session, user.id)

    assert credits_service.get_balance(db_session, user.id) == 5


def test_credit_increases_balance(db_session):
    user = factories.create_user(db_session)

    balance = credits_service.credit(db_session, user.id, 30)

    assert balance == 30
    assert credits_service.get_balance(db_session, user.id) == 30


def test_credit_accumulates_across_calls(db_session):
    user = factories.create_user(db_session)

    credits_service.credit(db_session, user.id, 10)
    balance = credits_service.credit(db_session, user.id, 5)

    assert balance == 15


def test_try_debit_succeeds_when_balance_is_sufficient(db_session):
    user = factories.create_user(db_session)
    credits_service.credit(db_session, user.id, 5)

    balance = credits_service.try_debit(db_session, user.id, 3)

    assert balance == 2
    assert credits_service.get_balance(db_session, user.id) == 2


def test_try_debit_succeeds_when_balance_exactly_matches_cost(db_session):
    user = factories.create_user(db_session)
    credits_service.credit(db_session, user.id, 1)

    balance = credits_service.try_debit(db_session, user.id, 1)

    assert balance == 0
    assert credits_service.try_debit(db_session, user.id, 1) is None


def test_try_debit_fails_when_balance_is_insufficient(db_session):
    user = factories.create_user(db_session)
    credits_service.credit(db_session, user.id, 1)

    result = credits_service.try_debit(db_session, user.id, 2)

    assert result is None
    # Nada foi alterado: o WHERE do UPDATE atômico não bateu.
    assert credits_service.get_balance(db_session, user.id) == 1


def test_try_debit_never_makes_balance_negative_for_a_fresh_user(
    db_session,
):
    user = factories.create_user(db_session)

    result = credits_service.try_debit(db_session, user.id, 1)

    assert result is None
    assert credits_service.get_balance(db_session, user.id) == 0


def test_balance_is_scoped_per_user(db_session):
    user_a = factories.create_user(db_session)
    user_b = factories.create_user(db_session)

    credits_service.credit(db_session, user_a.id, 10)

    assert credits_service.get_balance(db_session, user_a.id) == 10
    assert credits_service.get_balance(db_session, user_b.id) == 0


# --- record_apple_purchase: ledger + crédito na mesma transação ---


def test_record_apple_purchase_grants_the_configured_credits(db_session):
    user = factories.create_user(db_session)

    balance, already_processed = credits_service.record_apple_purchase(
        db_session,
        user_id=user.id,
        apple_transaction_id="txn-unit-1",
        apple_original_transaction_id="txn-unit-1",
        product_id="lys.com.career-app.credits.10",
        credits_granted=10,
        environment="Sandbox",
    )

    assert balance == 10
    assert already_processed is False
    assert credits_service.get_balance(db_session, user.id) == 10


def test_record_apple_purchase_is_idempotent_for_the_same_transaction_id(
    db_session,
):
    user = factories.create_user(db_session)

    credits_service.record_apple_purchase(
        db_session,
        user_id=user.id,
        apple_transaction_id="txn-unit-dup",
        apple_original_transaction_id="txn-unit-dup",
        product_id="lys.com.career-app.credits.10",
        credits_granted=10,
        environment="Sandbox",
    )

    balance, already_processed = credits_service.record_apple_purchase(
        db_session,
        user_id=user.id,
        apple_transaction_id="txn-unit-dup",
        apple_original_transaction_id="txn-unit-dup",
        product_id="lys.com.career-app.credits.10",
        credits_granted=10,
        environment="Sandbox",
    )

    # Idempotente: o saldo continua 10, não 20.
    assert balance == 10
    assert already_processed is True


def test_record_apple_purchase_persists_the_ledger_row(db_session):
    from app.credits.models import AICreditPurchase

    user = factories.create_user(db_session)

    credits_service.record_apple_purchase(
        db_session,
        user_id=user.id,
        apple_transaction_id="txn-unit-ledger",
        apple_original_transaction_id="txn-unit-ledger",
        product_id="lys.com.career-app.credits.30",
        credits_granted=30,
        environment="Production",
    )

    purchase = (
        db_session.query(AICreditPurchase)
        .filter(
            AICreditPurchase.apple_transaction_id
            == "txn-unit-ledger"
        )
        .one()
    )

    assert purchase.user_id == user.id
    assert purchase.credits_granted == 30
    assert purchase.environment == "Production"
