from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.auth import refresh_token_service
from app.auth.models import RefreshToken
from tests import factories

pytestmark = pytest.mark.unit


def test_hash_refresh_token_is_deterministic():
    assert refresh_token_service.hash_refresh_token(
        "same-token"
    ) == refresh_token_service.hash_refresh_token("same-token")


def test_hash_refresh_token_differs_for_different_input():
    assert refresh_token_service.hash_refresh_token(
        "token-a"
    ) != refresh_token_service.hash_refresh_token("token-b")


def test_create_refresh_token_stores_hash_not_raw_value(db_session, user):
    raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=user.id
    )
    db_session.commit()

    stored = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id)
        .first()
    )

    assert stored is not None
    assert stored.token_hash != raw_token
    assert stored.token_hash == refresh_token_service.hash_refresh_token(
        raw_token
    )


def test_rotate_refresh_token_returns_new_token_and_same_user(
    db_session, user
):
    raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=user.id
    )
    db_session.commit()

    returned_user_id, new_raw_token = refresh_token_service.rotate_refresh_token(
        db_session, raw_token
    )

    assert returned_user_id == user.id
    assert new_raw_token != raw_token


def test_rotate_refresh_token_marks_old_token_as_revoked(db_session, user):
    raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=user.id
    )
    db_session.commit()

    refresh_token_service.rotate_refresh_token(db_session, raw_token)

    old_token = (
        db_session.query(RefreshToken)
        .filter(
            RefreshToken.token_hash
            == refresh_token_service.hash_refresh_token(raw_token)
        )
        .first()
    )
    assert old_token.revoked_at is not None


def test_rotate_refresh_token_rejects_unknown_token(db_session):
    with pytest.raises(HTTPException) as exc_info:
        refresh_token_service.rotate_refresh_token(
            db_session, "totally-unknown-token"
        )

    assert exc_info.value.status_code == 401


def test_rotate_refresh_token_rejects_expired_token(db_session, user):
    raw_token = "an-expired-raw-token"
    factories.create_refresh_token_row(
        db_session,
        user,
        token_hash=refresh_token_service.hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        refresh_token_service.rotate_refresh_token(db_session, raw_token)

    assert exc_info.value.status_code == 401


def test_rotate_refresh_token_reuse_revokes_entire_family(db_session, user):
    raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=user.id
    )
    db_session.commit()

    _, rotated_token = refresh_token_service.rotate_refresh_token(
        db_session, raw_token
    )

    with pytest.raises(HTTPException) as exc_info:
        refresh_token_service.rotate_refresh_token(db_session, raw_token)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        refresh_token_service.rotate_refresh_token(db_session, rotated_token)
    assert exc_info.value.status_code == 401


def test_revoke_all_refresh_tokens_for_user_revokes_active_tokens(
    db_session, user
):
    raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=user.id
    )
    db_session.commit()

    refresh_token_service.revoke_all_refresh_tokens_for_user(
        db_session, user.id
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        refresh_token_service.rotate_refresh_token(db_session, raw_token)
    assert exc_info.value.status_code == 401


def test_revoke_all_refresh_tokens_does_not_affect_other_users(
    db_session, user, second_user
):
    other_raw_token = refresh_token_service.create_refresh_token(
        db=db_session, user_id=second_user.id
    )
    db_session.commit()

    refresh_token_service.revoke_all_refresh_tokens_for_user(
        db_session, user.id
    )
    db_session.commit()

    returned_user_id, _ = refresh_token_service.rotate_refresh_token(
        db_session, other_raw_token
    )
    assert returned_user_id == second_user.id
