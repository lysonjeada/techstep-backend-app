from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.auth import verification_service
from tests import factories

pytestmark = pytest.mark.unit


def test_generate_verification_code_is_six_digits():
    code = verification_service.generate_verification_code()

    assert len(code) == 6
    assert code.isdigit()


def test_hash_verification_code_is_deterministic():
    assert verification_service.hash_verification_code(
        "123456"
    ) == verification_service.hash_verification_code("123456")


def test_hash_verification_code_differs_for_different_codes():
    assert verification_service.hash_verification_code(
        "111111"
    ) != verification_service.hash_verification_code("222222")


def test_create_and_validate_correct_code_marks_user_verified(
    db_session, user
):
    user.is_email_verified = False
    db_session.commit()

    code = verification_service.create_verification_code(db_session, user)

    verification_service.validate_verification_code(db_session, user, code)

    assert user.is_email_verified is True


def test_validate_wrong_code_raises_400_and_increments_attempts(
    db_session, user
):
    verification_service.create_verification_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        verification_service.validate_verification_code(
            db_session, user, "000000"
        )

    assert exc_info.value.status_code == 400

    stored = verification_service.get_latest_active_code(db_session, user.id)
    assert stored.attempts == 1


def test_validate_code_blocks_after_max_attempts(db_session, user):
    verification_service.create_verification_code(db_session, user)

    for _ in range(verification_service.MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            verification_service.validate_verification_code(
                db_session, user, "000000"
            )

    with pytest.raises(HTTPException) as exc_info:
        verification_service.validate_verification_code(
            db_session, user, "000000"
        )

    assert exc_info.value.status_code == 429


def test_validate_expired_code_raises_400(db_session, user):
    from app.auth.models import EmailVerificationCode

    code = "654321"
    verification = EmailVerificationCode(
        user_id=user.id,
        code_hash=verification_service.hash_verification_code(code),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        last_sent_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        attempts=0,
        is_used=False,
    )
    db_session.add(verification)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        verification_service.validate_verification_code(
            db_session, user, code
        )

    assert exc_info.value.status_code == 400


def test_validate_code_with_no_active_code_raises_400(db_session, user):
    with pytest.raises(HTTPException) as exc_info:
        verification_service.validate_verification_code(
            db_session, user, "123456"
        )

    assert exc_info.value.status_code == 400


def test_create_verification_code_invalidates_previous_code(
    db_session, user
):
    first_code = verification_service.create_verification_code(
        db_session, user
    )
    verification_service.create_verification_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        verification_service.validate_verification_code(
            db_session, user, first_code
        )

    assert exc_info.value.status_code == 400


def test_get_resend_wait_seconds_is_zero_when_no_previous_code():
    assert verification_service.get_resend_wait_seconds(None) == 0


def test_create_resend_code_blocked_within_cooldown(db_session, user):
    verification_service.create_verification_code(db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        verification_service.create_resend_code(db_session, user)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_create_resend_code_allowed_after_cooldown_elapsed(db_session, user):
    verification_service.create_verification_code(db_session, user)

    latest = verification_service.get_latest_active_code(db_session, user.id)
    latest.last_sent_at = datetime.now(timezone.utc) - timedelta(
        seconds=verification_service.RESEND_SECONDS + 1
    )
    db_session.commit()

    new_code, wait_seconds = verification_service.create_resend_code(
        db_session, user
    )

    assert len(new_code) == 6
    assert wait_seconds == verification_service.RESEND_SECONDS
