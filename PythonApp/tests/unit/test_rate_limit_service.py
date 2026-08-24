"""Testes unitários do algoritmo de rate limiting (janela fixa em
Postgres). Cobertura do comportamento HTTP real (por endpoint) fica em
tests/security/test_rate_limiting_http.py — aqui é só a lógica pura de
`check_rate_limit`, testada diretamente contra o banco de teste, sem
subir a aplicação inteira.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.rate_limit import service as rate_limit_service

pytestmark = pytest.mark.unit


def test_allows_requests_up_to_the_limit(db_session):
    key = "unit-test:below-limit"

    for _ in range(3):
        rate_limit_service.check_rate_limit(db_session, key, 3, 60)


def test_blocks_request_that_exceeds_the_limit(db_session):
    key = "unit-test:exceeds-limit"

    for _ in range(3):
        rate_limit_service.check_rate_limit(db_session, key, 3, 60)

    with pytest.raises(HTTPException) as exc_info:
        rate_limit_service.check_rate_limit(db_session, key, 3, 60)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_retry_after_is_a_positive_number_within_the_window(db_session):
    key = "unit-test:retry-after"

    for _ in range(2):
        rate_limit_service.check_rate_limit(db_session, key, 2, 30)

    with pytest.raises(HTTPException) as exc_info:
        rate_limit_service.check_rate_limit(db_session, key, 2, 30)

    retry_after = int(exc_info.value.headers["Retry-After"])
    assert 0 < retry_after <= 30


def test_different_keys_have_independent_counters(db_session):
    key_a = "unit-test:tenant-a"
    key_b = "unit-test:tenant-b"

    for _ in range(3):
        rate_limit_service.check_rate_limit(db_session, key_a, 3, 60)

    with pytest.raises(HTTPException):
        rate_limit_service.check_rate_limit(db_session, key_a, 3, 60)

    # key_b nunca foi usada: seu orçamento é independente do de key_a.
    rate_limit_service.check_rate_limit(db_session, key_b, 3, 60)


def test_window_resets_after_it_expires(db_session, monkeypatch):
    key = "unit-test:window-reset"
    base_time = datetime.now(timezone.utc)

    monkeypatch.setattr(
        rate_limit_service, "_now", lambda: base_time
    )

    for _ in range(2):
        rate_limit_service.check_rate_limit(db_session, key, 2, 30)

    with pytest.raises(HTTPException):
        rate_limit_service.check_rate_limit(db_session, key, 2, 30)

    # Avança o relógio (mockado) para depois do fim da janela, sem
    # usar sleep real.
    monkeypatch.setattr(
        rate_limit_service,
        "_now",
        lambda: base_time + timedelta(seconds=31),
    )

    # A janela expirou: o contador reinicia e a chamada é permitida.
    rate_limit_service.check_rate_limit(db_session, key, 2, 30)


def test_concurrent_requests_within_same_window_are_all_counted(
    db_session,
):
    key = "unit-test:accumulate"

    for _ in range(5):
        rate_limit_service.check_rate_limit(db_session, key, 10, 60)

    row = db_session.execute(
        text(
            "SELECT count FROM rate_limit_buckets WHERE key = :key"
        ),
        {"key": key},
    ).first()

    assert row.count == 5
