import os
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from uuid import UUID

import jwt
from dotenv import load_dotenv
from jwt.exceptions import InvalidTokenError


load_dotenv()


JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
)

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256",
)

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "60",
    )
)


def create_access_token(
    user_id: UUID,
) -> str:
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY não foi configurada."
        )

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": (
            now
            + timedelta(
                minutes=(
                    JWT_ACCESS_TOKEN_EXPIRE_MINUTES
                )
            )
        ),
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(
    token: str,
) -> UUID:
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY não foi configurada."
        )

    payload = jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
    )

    subject = payload.get("sub")

    if not subject:
        raise InvalidTokenError(
            "Token sem identificador de usuário."
        )

    try:
        return UUID(subject)
    except ValueError as error:
        raise InvalidTokenError(
            "Identificador de usuário inválido."
        ) from error