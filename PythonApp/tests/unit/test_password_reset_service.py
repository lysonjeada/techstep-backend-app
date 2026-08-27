from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.auth import password_reset_service
from app.auth.models import PasswordResetCode, PasswordResetToken

pytestmark = pytest.mark.unit


def test_generate_reset_code_is_six_digits():
    code = password_reset_service.generate_reset_code()

    assert len(code) == 6
    assert code.isdigit()


def test_hash_reset_code_is_deterministic():
    assert password_reset_service.hash_reset_code(
        "123456"
    ) == password_reset_service.hash_reset_code("123456")


def test_hash_reset_code_differs_for_different_codes():
    assert password_reset_service.hash_reset_code(
        "111111"
    ) != password_reset_service.hash_reset_code("222222")


def test_hash_reset_token_is_deterministic_sha256():
    import hashlib

    token = "raw-token-value"
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()

    assert password_reset_service.hash_reset_token(token) == expected


def test_create_reset_code_stores_only_hash_not_plaintext(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)

    stored = password_reset_service.get_latest_active_code(
        db_session, user.id
    )

    assert stored is not None
    assert stored.code_hash != code
    assert stored.code_hash == password_reset_service.hash_reset_code(code)


def test_create_reset_code_sets_expiration(db_session, user):
    before = datetime.now(timezone.utc)

    password_reset_service.create_reset_code(db_session, user)

    stored = password_reset_service.get_latest_active_code(
        db_session, user.id
    )

    expected_expiry = before + timedelta(
        minutes=password_reset_service.CODE_EXPIRATION_MINUTES
    )

    # Margem de alguns segundos para o tempo de execução do teste.
    assert abs(
        (stored.expires_at - expected_expiry).total_seconds()
    ) < 5


def test_create_reset_code_invalidates_previous_code(db_session, user):
    first_code = password_reset_service.create_reset_code(db_session, user)
    password_reset_service.create_reset_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.validate_reset_code_and_issue_token(
            db_session, user, first_code
        )

    assert exc_info.value.status_code == 400


def test_validate_correct_code_issues_reset_token(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)

    reset_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    assert isinstance(reset_token, str)
    assert len(reset_token) > 20

    stored_token = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .first()
    )
    assert stored_token is not None
    assert stored_token.token_hash != reset_token
    assert stored_token.used_at is None


def test_validate_correct_code_marks_code_used(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)
    password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    stored = (
        db_session.query(PasswordResetCode)
        .filter(PasswordResetCode.user_id == user.id)
        .first()
    )
    assert stored.is_used is True


def test_validate_wrong_code_raises_400_and_increments_attempts(
    db_session, user
):
    password_reset_service.create_reset_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.validate_reset_code_and_issue_token(
            db_session, user, "000000"
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == password_reset_service.INVALID_CODE_MESSAGE

    stored = password_reset_service.get_latest_active_code(
        db_session, user.id
    )
    assert stored.attempts == 1


def test_validate_code_blocks_after_max_attempts(db_session, user):
    password_reset_service.create_reset_code(db_session, user)

    for _ in range(password_reset_service.CODE_MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            password_reset_service.validate_reset_code_and_issue_token(
                db_session, user, "000000"
            )

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.validate_reset_code_and_issue_token(
            db_session, user, "000000"
        )

    assert exc_info.value.status_code == 429


def test_validate_expired_code_raises_400(db_session, user):
    code = "654321"
    reset_code = PasswordResetCode(
        user_id=user.id,
        code_hash=password_reset_service.hash_reset_code(code),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        last_sent_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        attempts=0,
        is_used=False,
    )
    db_session.add(reset_code)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.validate_reset_code_and_issue_token(
            db_session, user, code
        )

    assert exc_info.value.status_code == 400


def test_validate_code_with_no_active_code_raises_400(db_session, user):
    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.validate_reset_code_and_issue_token(
            db_session, user, "123456"
        )

    assert exc_info.value.status_code == 400


def test_create_resend_code_blocked_within_cooldown(db_session, user):
    password_reset_service.create_reset_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.create_resend_code(db_session, user)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_create_resend_code_allowed_after_cooldown_elapsed(db_session, user):
    password_reset_service.create_reset_code(db_session, user)

    latest = password_reset_service.get_latest_active_code(
        db_session, user.id
    )
    latest.last_sent_at = datetime.now(timezone.utc) - timedelta(
        seconds=password_reset_service.CODE_RESEND_SECONDS + 1
    )
    db_session.commit()

    new_code, wait_seconds = password_reset_service.create_resend_code(
        db_session, user
    )

    assert len(new_code) == 6
    assert wait_seconds == password_reset_service.CODE_RESEND_SECONDS


# --- consume_reset_token ---


def test_consume_reset_token_with_valid_token_returns_user(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)
    raw_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    resolved_user = password_reset_service.consume_reset_token(
        db_session, raw_token
    )

    assert resolved_user.id == user.id


def test_consume_reset_token_does_not_store_raw_token(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)
    raw_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    stored = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .first()
    )

    assert stored.token_hash != raw_token
    assert raw_token not in stored.token_hash


def test_consume_reset_token_with_invalid_token_raises_400(db_session):
    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.consume_reset_token(
            db_session, "does-not-exist"
        )

    assert exc_info.value.status_code == 400


def test_consume_reset_token_with_expired_token_raises_400(db_session, user):
    token = PasswordResetToken(
        user_id=user.id,
        token_hash=password_reset_service.hash_reset_token("expired-token"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(token)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.consume_reset_token(
            db_session, "expired-token"
        )

    assert exc_info.value.status_code == 400


def test_consume_reset_token_cannot_be_reused(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)
    raw_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    password_reset_service.consume_reset_token(db_session, raw_token)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        password_reset_service.consume_reset_token(db_session, raw_token)

    assert exc_info.value.status_code == 400


def test_consume_reset_token_does_not_commit(db_session, user):
    """consume_reset_token só muda o objeto em memória — quem chama
    decide o commit, porque a troca de senha completa precisa ser
    atômica (ver reset_password no router)."""

    code = password_reset_service.create_reset_code(db_session, user)
    raw_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    password_reset_service.consume_reset_token(db_session, raw_token)
    db_session.rollback()

    # Sem commit, o rollback desfaz o used_at — o token continua válido.
    resolved_user = password_reset_service.consume_reset_token(
        db_session, raw_token
    )
    assert resolved_user.id == user.id


def test_invalidate_active_reset_artifacts_for_user(db_session, user):
    code = password_reset_service.create_reset_code(db_session, user)
    raw_token = password_reset_service.validate_reset_code_and_issue_token(
        db_session, user, code
    )

    # Uma segunda solicitação de código, abandonada.
    password_reset_service.create_reset_code(db_session, user)

    password_reset_service.invalidate_active_reset_artifacts_for_user(
        db_session, user.id
    )
    db_session.commit()

    with pytest.raises(HTTPException):
        password_reset_service.consume_reset_token(db_session, raw_token)

    remaining_active_code = password_reset_service.get_latest_active_code(
        db_session, user.id
    )
    assert remaining_active_code is None
