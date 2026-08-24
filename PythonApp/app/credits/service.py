from dataclasses import dataclass, field
from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as app_models
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.observability import logger
from app.rate_limit.service import increment_and_get_count

from .config import (
    AI_CREDIT_FREE_LIMIT,
    AI_CREDIT_FREE_WINDOW_SECONDS,
    AI_FEATURE_COSTS,
)


# --- saldo: upsert idempotente, débito e crédito atômicos ---
#
# Nenhuma dessas operações usa "SELECT saldo, depois UPDATE" — isso teria
# race condition sob concorrência. Tudo é um único UPDATE/INSERT atômico
# no Postgres, com o resultado (ou a ausência dele) decidindo o que
# aconteceu.


_ENSURE_ROW_SQL = text(
    """
    INSERT INTO ai_credit_balances (user_id, balance, updated_at)
    VALUES (:user_id, 0, now())
    ON CONFLICT (user_id) DO NOTHING
    """
)

_TRY_DEBIT_SQL = text(
    """
    UPDATE ai_credit_balances
    SET balance = balance - :cost, updated_at = now()
    WHERE user_id = :user_id AND balance >= :cost
    RETURNING balance
    """
)

_CREDIT_SQL = text(
    """
    UPDATE ai_credit_balances
    SET balance = balance + :amount, updated_at = now()
    WHERE user_id = :user_id
    RETURNING balance
    """
)


def _ensure_balance_row_no_commit(db: Session, user_id: UUID) -> None:
    db.execute(_ENSURE_ROW_SQL, {"user_id": str(user_id)})


def ensure_balance_row(db: Session, user_id: UUID) -> None:
    """Garante que o usuário tem uma linha de saldo (balance=0), sem
    sobrescrever um saldo já existente. Cobre usuários criados antes
    desta feature existir, sem precisar de backfill de migration."""

    _ensure_balance_row_no_commit(db, user_id)
    db.commit()


def get_balance(db: Session, user_id: UUID) -> int:
    ensure_balance_row(db, user_id)

    row = db.execute(
        text(
            "SELECT balance FROM ai_credit_balances WHERE user_id = :user_id"
        ),
        {"user_id": str(user_id)},
    ).first()

    return row.balance if row else 0


def try_debit(db: Session, user_id: UUID, cost: int) -> int | None:
    """Debita `cost` créditos atomicamente. Retorna o saldo resultante,
    ou None se o saldo era insuficiente (nada foi alterado)."""

    _ensure_balance_row_no_commit(db, user_id)

    row = db.execute(
        _TRY_DEBIT_SQL,
        {"user_id": str(user_id), "cost": cost},
    ).first()

    db.commit()

    return row.balance if row else None


def _credit_no_commit(db: Session, user_id: UUID, amount: int) -> int:
    _ensure_balance_row_no_commit(db, user_id)

    row = db.execute(
        _CREDIT_SQL,
        {"user_id": str(user_id), "amount": amount},
    ).first()

    return row.balance


def credit(db: Session, user_id: UUID, amount: int) -> int:
    """Adiciona `amount` créditos (reembolso de consumo com falha
    técnica). Retorna o saldo resultante."""

    balance = _credit_no_commit(db, user_id, amount)
    db.commit()

    return balance


def record_apple_purchase(
    db: Session,
    *,
    user_id: UUID,
    apple_transaction_id: str,
    apple_original_transaction_id: str | None,
    product_id: str,
    credits_granted: int,
    environment: str,
) -> tuple[int, bool]:
    """Registra a compra no ledger (`AICreditPurchase`) e credita o saldo
    NA MESMA TRANSAÇÃO — um só commit para os dois, nunca um sem o
    outro. `apple_transaction_id` é UNIQUE: se a linha já existir (POST
    duplicado, seja retry do device StoreKit ou requisições concorrentes
    com a mesma transação), o INSERT falha com IntegrityError, nada é
    alterado, e devolvemos o saldo atual como idempotente.

    Retorna (balance, already_processed).
    """

    # Import local evita import circular entre service.py e models.py
    # (models.py não depende de service.py, mas mantém o padrão do
    # projeto de cada módulo importar só o que usa).
    from .models import AICreditPurchase

    purchase = AICreditPurchase(
        user_id=user_id,
        apple_transaction_id=apple_transaction_id,
        apple_original_transaction_id=apple_original_transaction_id,
        product_id=product_id,
        credits_granted=credits_granted,
        environment=environment,
    )

    db.add(purchase)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()

        return get_balance(db, user_id), True

    balance = _credit_no_commit(db, user_id, credits_granted)
    db.commit()

    return balance, False


# --- gate de consumo: estende o rate limit existente com créditos ---


def _is_user_caused_error(error: BaseException) -> bool:
    """True para erros que o próprio usuário causou (corpo inválido,
    regra de negócio rejeitada dentro do handler) — esses NÃO geram
    reembolso. Falhas técnicas (erro do SDK da OpenAI, erro de banco,
    timeout, ou qualquer coisa que o handler devolva como 5xx) geram
    reembolso do crédito debitado nesta requisição."""

    return (
        isinstance(error, HTTPException)
        and error.status_code < 500
    )


@dataclass
class CreditGateState:
    current_user: app_models.User
    scope: str
    cost: int
    credit_consumed: bool = field(default=False)


def ai_credit_gate(
    scope: str,
    cost: int | None = None,
    free_limit: int | None = None,
    window_seconds: int | None = None,
):
    """Dependency factory usada nos endpoints de IA no lugar de
    ip_rate_limiter. Estende o rate limit existente (mesma janela fixa
    em Postgres) com uma condição: quando a janela gratuita por usuário
    estoura, em vez de bloquear com 429, debita créditos comprados; se
    não houver saldo, bloqueia com 402 INSUFFICIENT_AI_CREDITS.

    Como toda dependency com yield do FastAPI, o código após o `yield`
    roda depois do handler da rota terminar — inclusive quando ele
    levanta uma exceção, que é relançada dentro do bloco `except` via
    `athrow()`. É esse mecanismo que permite reembolsar o crédito
    automaticamente quando a chamada de IA falha por um motivo técnico
    (nunca quando é um erro de validação do próprio usuário).

    Comportamento herdado do rate limiter original, não é regressão:
    como as dependencies resolvem antes da validação de Form()/corpo da
    própria rota, o contador (e um eventual débito) já aconteceu mesmo
    que a rota rejeite a requisição com 422 logo em seguida.
    """

    resolved_cost = cost if cost is not None else AI_FEATURE_COSTS[scope]
    resolved_free_limit = (
        free_limit if free_limit is not None else AI_CREDIT_FREE_LIMIT
    )
    resolved_window_seconds = (
        window_seconds
        if window_seconds is not None
        else AI_CREDIT_FREE_WINDOW_SECONDS
    )

    async def _dependency(
        db: Session = Depends(get_db),
        current_user: app_models.User = Depends(get_current_user),
    ) -> AsyncGenerator[CreditGateState, None]:
        state = CreditGateState(
            current_user=current_user,
            scope=scope,
            cost=resolved_cost,
        )

        key = f"{scope}:user:{current_user.id}"

        count, _ = increment_and_get_count(
            db, key, resolved_window_seconds
        )

        if count > resolved_free_limit:
            new_balance = try_debit(
                db, current_user.id, resolved_cost
            )

            if new_balance is None:
                logger.info(
                    "ai credit insufficient balance",
                    extra={
                        "event": "ai_credit_insufficient",
                        "userId": str(current_user.id),
                        "scope": scope,
                        "cost": resolved_cost,
                    },
                )

                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "code": "INSUFFICIENT_AI_CREDITS",
                        "message": "Créditos de IA insuficientes.",
                    },
                )

            state.credit_consumed = True

            logger.info(
                "ai credit consumed",
                extra={
                    "event": "ai_credit_consumed",
                    "userId": str(current_user.id),
                    "scope": scope,
                    "cost": resolved_cost,
                    "balanceAfter": new_balance,
                },
            )

        try:
            yield state
        except Exception as error:
            if state.credit_consumed and not _is_user_caused_error(
                error
            ):
                balance_after_refund = credit(
                    db, current_user.id, resolved_cost
                )

                logger.info(
                    "ai credit refunded",
                    extra={
                        "event": "ai_credit_refunded",
                        "userId": str(current_user.id),
                        "scope": scope,
                        "cost": resolved_cost,
                        "balanceAfter": balance_after_refund,
                    },
                )

            raise

    return _dependency
