from fastapi import (
    Depends,
    HTTPException,
    status,
)
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app import models
from app.auth.security import (
    hash_password,
    verify_password as verify_password_hash,
)
from app.auth.token_service import (
    decode_access_token,
)
from app.database import get_db


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/users/login/",
)

# auto_error=False: não levanta 401 quando não há header Authorization
# (ou é inválido) — usado em rotas públicas que só precisam saber
# QUEM é o usuário quando ele está logado (ex.: favoritos de artigo),
# sem exigir login para acessar o recurso em si.
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/users/login/",
    auto_error=False,
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Não foi possível validar "
            "as credenciais."
        ),
        headers={
            "WWW-Authenticate": "Bearer"
        },
    )

    try:
        user_id = decode_access_token(
            token
        )
    except (
        InvalidTokenError,
        ValueError,
    ) as error:
        raise credentials_error from error

    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id
        )
        .first()
    )

    if user is None:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário desativado.",
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Confirme seu e-mail antes "
                "de continuar."
            ),
        )

    return user


def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> models.User | None:
    # Só a AUSÊNCIA de token é "convidado, sem erro". Um token
    # presente mas expirado/inválido continua levantando 401 — se
    # engolíssemos esse erro também, o cliente nunca saberia que
    # precisa renovar o token (a renovação automática do app só
    # dispara reagindo a um 401; sem ele, o servidor voltaria a
    # tratar um usuário LOGADO como anônimo silenciosamente sempre
    # que o access token vencesse, ex.: devolvendo is_favorited=false
    # para quem já favoritou o recurso).
    if not token:
        return None

    return get_current_user(
        token=token,
        db=db,
    )


# Compatibilidade com imports antigos.

def get_password_hash(
    password: str,
) -> str:
    return hash_password(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return verify_password_hash(
        plain_password,
        hashed_password,
    )