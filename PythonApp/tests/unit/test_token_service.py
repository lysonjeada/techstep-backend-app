import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth import token_service

pytestmark = pytest.mark.unit


def test_create_and_decode_access_token_roundtrip():
    user_id = uuid.uuid4()

    token = token_service.create_access_token(user_id)
    decoded_user_id = token_service.decode_access_token(token)

    assert decoded_user_id == user_id


def test_access_token_contains_expected_claims():
    user_id = uuid.uuid4()

    token = token_service.create_access_token(user_id)
    payload = jwt.decode(
        token,
        token_service.JWT_SECRET_KEY,
        algorithms=[token_service.JWT_ALGORITHM],
    )

    assert payload["sub"] == str(user_id)
    assert "iat" in payload
    assert "exp" in payload


def test_decode_access_token_rejects_expired_token():
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now - timedelta(minutes=120),
            "exp": now - timedelta(minutes=60),
        },
        token_service.JWT_SECRET_KEY,
        algorithm=token_service.JWT_ALGORITHM,
    )

    with pytest.raises(jwt.exceptions.InvalidTokenError):
        token_service.decode_access_token(expired_token)


def test_decode_access_token_rejects_token_without_sub():
    now = datetime.now(timezone.utc)
    token_without_sub = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=60)},
        token_service.JWT_SECRET_KEY,
        algorithm=token_service.JWT_ALGORITHM,
    )

    with pytest.raises(jwt.exceptions.InvalidTokenError):
        token_service.decode_access_token(token_without_sub)


def test_decode_access_token_rejects_non_uuid_sub():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "not-a-uuid", "iat": now, "exp": now + timedelta(minutes=60)},
        token_service.JWT_SECRET_KEY,
        algorithm=token_service.JWT_ALGORITHM,
    )

    with pytest.raises(jwt.exceptions.InvalidTokenError):
        token_service.decode_access_token(token)


def test_decode_access_token_rejects_token_signed_with_wrong_key():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "a-completely-different-secret-key",
        algorithm=token_service.JWT_ALGORITHM,
    )

    with pytest.raises(jwt.exceptions.InvalidTokenError):
        token_service.decode_access_token(token)


def test_decode_access_token_rejects_malformed_token():
    with pytest.raises(jwt.exceptions.InvalidTokenError):
        token_service.decode_access_token("not-a-jwt-at-all")
