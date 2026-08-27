import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import PasswordResetCode, PasswordResetToken
from app.models import User


CODE_EXPIRATION_MINUTES = int(
    os.getenv(
        "PASSWORD_RESET_CODE_EXPIRATION_MINUTES",
        "10",
    )
)

CODE_RESEND_SECONDS = int(
    os.getenv(
        "PASSWORD_RESET_CODE_RESEND_SECONDS",
        "60",
    )
)

CODE_MAX_ATTEMPTS = int(
    os.getenv(
        "PASSWORD_RESET_CODE_MAX_ATTEMPTS",
        "5",
    )
)

TOKEN_EXPIRATION_MINUTES = int(
    os.getenv(
        "PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES",
        "10",
    )
)

# Reaproveita a mesma pepper do e-mail de verificação de cadastro —
# ambas hasheiam um código numérico de 6 dígitos com o mesmo nível de
# sensibilidade, e assim não exigimos uma nova secret em produção só
# para este fluxo.
RESET_PEPPER = os.getenv(
    "EMAIL_VERIFICATION_PEPPER",
    "",
)

INVALID_CODE_MESSAGE = "Código inválido ou expirado."
INVALID_TOKEN_MESSAGE = "Token inválido ou expirado."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_reset_code() -> str:
    number = secrets.randbelow(1_000_000)

    return f"{number:06d}"


def hash_reset_code(
    code: str,
) -> str:
    if not RESET_PEPPER:
        raise RuntimeError(
            "EMAIL_VERIFICATION_PEPPER não configurado."
        )

    value = (
        f"{code}:{RESET_PEPPER}"
    ).encode("utf-8")

    return hashlib.sha256(value).hexdigest()


def hash_reset_token(
    token: str,
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def invalidate_previous_codes(
    db: Session,
    user_id: UUID,
) -> None:
    db.query(
        PasswordResetCode
    ).filter(
        PasswordResetCode.user_id
        == user_id,
        PasswordResetCode.is_used
        == False,  # noqa: E712
    ).update(
        {
            PasswordResetCode.is_used:
                True
        },
        synchronize_session=False,
    )


def create_reset_code(
    db: Session,
    user: User,
) -> str:
    invalidate_previous_codes(
        db=db,
        user_id=user.id,
    )

    code = generate_reset_code()
    now = utc_now()

    reset_code = PasswordResetCode(
        user_id=user.id,
        code_hash=hash_reset_code(code),
        expires_at=(
            now
            + timedelta(
                minutes=CODE_EXPIRATION_MINUTES
            )
        ),
        created_at=now,
        last_sent_at=now,
        attempts=0,
        is_used=False,
    )

    db.add(reset_code)
    db.commit()

    return code


def get_latest_active_code(
    db: Session,
    user_id: UUID,
) -> Optional[PasswordResetCode]:
    return (
        db.query(
            PasswordResetCode
        )
        .filter(
            PasswordResetCode.user_id
            == user_id,
            PasswordResetCode.is_used
            == False,  # noqa: E712
        )
        .order_by(
            PasswordResetCode.created_at
            .desc()
        )
        .first()
    )


def get_resend_wait_seconds(
    reset_code:
        Optional[PasswordResetCode],
) -> int:
    if reset_code is None:
        return 0

    elapsed = (
        utc_now()
        - reset_code.last_sent_at
    ).total_seconds()

    remaining = (
        CODE_RESEND_SECONDS
        - int(elapsed)
    )

    return max(0, remaining)


def create_resend_code(
    db: Session,
    user: User,
) -> Tuple[str, int]:
    latest = get_latest_active_code(
        db=db,
        user_id=user.id,
    )

    wait_seconds = get_resend_wait_seconds(
        latest
    )

    if wait_seconds > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Aguarde "
                f"{wait_seconds} segundos "
                "antes de solicitar outro código."
            ),
            headers={
                "Retry-After":
                    str(wait_seconds)
            },
        )

    code = create_reset_code(
        db=db,
        user=user,
    )

    return code, CODE_RESEND_SECONDS


def validate_reset_code_and_issue_token(
    db: Session,
    user: User,
    code: str,
) -> str:
    """Valida o código mais recente do usuário; se válido, consome o
    código e emite um reset token opaco de uso único. Comita a cada
    mutação (mesmo padrão de validate_verification_code) — esta etapa
    não precisa ser atômica com nada além de si mesma."""

    reset_code = get_latest_active_code(
        db=db,
        user_id=user.id,
    )

    invalid_error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=INVALID_CODE_MESSAGE,
    )

    if reset_code is None:
        raise invalid_error

    now = utc_now()

    if reset_code.expires_at <= now:
        reset_code.is_used = True
        db.commit()

        raise invalid_error

    if reset_code.attempts >= CODE_MAX_ATTEMPTS:
        reset_code.is_used = True
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Número máximo de tentativas "
                "atingido. Solicite um novo código."
            ),
        )

    received_hash = hash_reset_code(code)

    is_valid = hmac.compare_digest(
        received_hash,
        reset_code.code_hash,
    )

    if not is_valid:
        reset_code.attempts += 1
        db.commit()

        # Mensagem genérica de propósito — diferente do fluxo de
        # verificação de e-mail, não informamos tentativas restantes
        # aqui, só o essencial.
        raise invalid_error

    reset_code.is_used = True

    raw_token = secrets.token_urlsafe(32)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token(raw_token),
        expires_at=(
            now
            + timedelta(
                minutes=TOKEN_EXPIRATION_MINUTES
            )
        ),
    )

    db.add(reset_token)
    db.commit()

    return raw_token


def consume_reset_token(
    db: Session,
    raw_token: str,
) -> User:
    """Valida um reset token e marca como usado, mas NÃO comita — a
    troca de senha, a revogação dos refresh tokens e a invalidação de
    outras solicitações de reset precisam entrar na MESMA transação
    (ver reset_password no router). Quem chama decide o commit/rollback."""

    token_hash = hash_reset_token(raw_token)

    stored = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash
            == token_hash
        )
        .first()
    )

    invalid_error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=INVALID_TOKEN_MESSAGE,
    )

    if stored is None:
        raise invalid_error

    if stored.used_at is not None:
        raise invalid_error

    if stored.expires_at <= utc_now():
        raise invalid_error

    user = (
        db.query(User)
        .filter(User.id == stored.user_id)
        .first()
    )

    if user is None:
        raise invalid_error

    stored.used_at = utc_now()

    return user


def invalidate_active_reset_artifacts_for_user(
    db: Session,
    user_id: UUID,
) -> None:
    """Chamado só depois de um reset de senha bem-sucedido, na mesma
    transação: qualquer código ou token de reset ainda ativo desse
    usuário (de uma tentativa anterior abandonada) deixa de valer."""

    now = utc_now()

    db.query(
        PasswordResetCode
    ).filter(
        PasswordResetCode.user_id == user_id,
        PasswordResetCode.is_used == False,  # noqa: E712
    ).update(
        {PasswordResetCode.is_used: True},
        synchronize_session=False,
    )

    db.query(
        PasswordResetToken
    ).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    ).update(
        {PasswordResetToken.used_at: now},
        synchronize_session=False,
    )
