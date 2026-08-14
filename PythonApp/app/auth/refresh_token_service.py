import hashlib
import os
import secrets

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import UUID

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.auth.models import RefreshToken


REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv(
        "REFRESH_TOKEN_EXPIRE_DAYS",
        "30",
    )
)


def hash_refresh_token(
    token: str,
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_refresh_token(
    db: Session,
    user_id: UUID,
    family_id: UUID | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(
        64
    )

    token_hash = hash_refresh_token(
        raw_token
    )

    refresh_token = RefreshToken(
        user_id=user_id,
        family_id=(
            family_id
            or UUID(
                bytes=secrets.token_bytes(
                    16
                )
            )
        ),
        token_hash=token_hash,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(
                days=
                    REFRESH_TOKEN_EXPIRE_DAYS
            )
        ),
    )

    db.add(refresh_token)

    return raw_token

def rotate_refresh_token(
    db: Session,
    raw_token: str,
) -> tuple[UUID, str]:
    token_hash = hash_refresh_token(
        raw_token
    )

    stored_token = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash
            == token_hash
        )
        .first()
    )

    if stored_token is None:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Refresh token inválido.",
        )

    now = datetime.now(
        timezone.utc
    )

    if stored_token.revoked_at:
        # Token antigo reutilizado.
        # Revoga toda a família.
        (
            db.query(RefreshToken)
            .filter(
                RefreshToken.family_id
                == stored_token.family_id
            )
            .update(
                {
                    RefreshToken.revoked_at:
                        now
                },
                synchronize_session=False,
            )
        )

        db.commit()

        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Refresh token já utilizado."
            ),
        )

    if stored_token.expires_at <= now:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Refresh token expirado.",
        )

    stored_token.revoked_at = now

    new_token = create_refresh_token(
        db=db,
        user_id=stored_token.user_id,
        family_id=
            stored_token.family_id,
    )

    db.commit()

    return (
        stored_token.user_id,
        new_token,
    )