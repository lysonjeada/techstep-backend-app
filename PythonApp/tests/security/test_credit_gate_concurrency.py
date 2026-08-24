"""Prova, contra o Postgres real, que o débito atômico de créditos
(app.credits.service.try_debit) não permite overspend sob concorrência:
com saldo=1, duas requisições simultâneas só permitem uma debitar.

Diferente do resto da suíte, este teste NÃO usa a fixture `db_session`
(que compartilha uma única transação/savepoint por teste, serializada
em Python) — usa sessões e conexões de banco independentes de verdade,
em threads reais, para que a concorrência aconteça no nível do
Postgres. Uma race condition não pode ser provada serializando tudo
numa única sessão.
"""

import threading

import pytest

from app import models as app_models
from app.auth.security import hash_password
from app.credits import service as credits_service
from app.database import SessionLocal
from tests.factories import unique_suffix

pytestmark = pytest.mark.security


def _create_committed_user() -> app_models.User:
    db = SessionLocal()

    try:
        suffix = unique_suffix()

        user = app_models.User(
            email=f"concurrency-{suffix}@example.com",
            username=f"concurrency_{suffix}",
            hashed_password=hash_password("Senha123!"),
            is_active=True,
            is_email_verified=True,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user
    finally:
        db.close()


def _delete_user(user_id) -> None:
    db = SessionLocal()

    try:
        db.query(app_models.User).filter(
            app_models.User.id == user_id
        ).delete()

        db.commit()
    finally:
        db.close()


def test_concurrent_debits_never_overspend_a_balance_of_one():
    user = _create_committed_user()

    try:
        setup_db = SessionLocal()
        try:
            credits_service.credit(setup_db, user.id, 1)
        finally:
            setup_db.close()

        results: list[int | None] = [None, None]

        def _attempt_debit(index: int) -> None:
            db = SessionLocal()
            try:
                results[index] = credits_service.try_debit(
                    db, user.id, 1
                )
            finally:
                db.close()

        threads = [
            threading.Thread(target=_attempt_debit, args=(0,)),
            threading.Thread(target=_attempt_debit, args=(1,)),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        successes = [r for r in results if r is not None]
        failures = [r for r in results if r is None]

        assert len(successes) == 1
        assert len(failures) == 1
        assert successes[0] == 0

        verify_db = SessionLocal()
        try:
            final_balance = credits_service.get_balance(
                verify_db, user.id
            )
        finally:
            verify_db.close()

        assert final_balance == 0
    finally:
        _delete_user(user.id)


def test_concurrent_debits_with_sufficient_balance_both_succeed():
    """Contraprova: com saldo suficiente para as duas, nenhuma delas
    deveria ser bloqueada — a atomicidade não deve gerar falso
    positivo."""

    user = _create_committed_user()

    try:
        setup_db = SessionLocal()
        try:
            credits_service.credit(setup_db, user.id, 2)
        finally:
            setup_db.close()

        results: list[int | None] = [None, None]

        def _attempt_debit(index: int) -> None:
            db = SessionLocal()
            try:
                results[index] = credits_service.try_debit(
                    db, user.id, 1
                )
            finally:
                db.close()

        threads = [
            threading.Thread(target=_attempt_debit, args=(0,)),
            threading.Thread(target=_attempt_debit, args=(1,)),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert all(r is not None for r in results)

        verify_db = SessionLocal()
        try:
            final_balance = credits_service.get_balance(
                verify_db, user.id
            )
        finally:
            verify_db.close()

        assert final_balance == 0
    finally:
        _delete_user(user.id)
