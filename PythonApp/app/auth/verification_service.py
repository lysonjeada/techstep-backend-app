import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.models import EmailVerificationCode
from app.models import User


EXPIRATION_MINUTES = int(
    os.getenv(
        "EMAIL_VERIFICATION_EXPIRATION_MINUTES",
        "10",
    )
)

RESEND_SECONDS = int(
    os.getenv(
        "EMAIL_VERIFICATION_RESEND_SECONDS",
        "60",
    )
)

MAX_ATTEMPTS = int(
    os.getenv(
        "EMAIL_VERIFICATION_MAX_ATTEMPTS",
        "5",
    )
)

VERIFICATION_PEPPER = os.getenv(
    "EMAIL_VERIFICATION_PEPPER",
    "",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_verification_code() -> str:
    number = secrets.randbelow(1_000_000)

    return f"{number:06d}"


def hash_verification_code(
    code: str,
) -> str:
    if not VERIFICATION_PEPPER:
        raise RuntimeError(
            "EMAIL_VERIFICATION_PEPPER não configurado."
        )

    value = (
        f"{code}:{VERIFICATION_PEPPER}"
    ).encode("utf-8")

    return hashlib.sha256(value).hexdigest()


def invalidate_previous_codes(
    db: Session,
    user_id: UUID,
) -> None:
    db.query(
        EmailVerificationCode
    ).filter(
        EmailVerificationCode.user_id
        == user_id,
        EmailVerificationCode.is_used
        == False,  # noqa: E712
    ).update(
        {
            EmailVerificationCode.is_used:
                True
        },
        synchronize_session=False,
    )


def create_verification_code(
    db: Session,
    user: User,
) -> str:
    invalidate_previous_codes(
        db=db,
        user_id=user.id,
    )

    code = generate_verification_code()
    now = utc_now()

    verification = EmailVerificationCode(
        user_id=user.id,
        code_hash=hash_verification_code(
            code
        ),
        expires_at=(
            now
            + timedelta(
                minutes=EXPIRATION_MINUTES
            )
        ),
        created_at=now,
        last_sent_at=now,
        attempts=0,
        is_used=False,
    )

    db.add(verification)
    db.commit()

    return code


def get_latest_active_code(
    db: Session,
    user_id: UUID,
) -> Optional[EmailVerificationCode]:
    return (
        db.query(
            EmailVerificationCode
        )
        .filter(
            EmailVerificationCode.user_id
            == user_id,
            EmailVerificationCode.is_used
            == False,  # noqa: E712
        )
        .order_by(
            EmailVerificationCode.created_at
            .desc()
        )
        .first()
    )


def validate_verification_code(
    db: Session,
    user: User,
    code: str,
) -> None:
    verification = get_latest_active_code(
        db=db,
        user_id=user.id,
    )

    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Nenhum código de verificação "
                "ativo foi encontrado."
            ),
        )

    now = utc_now()

    if verification.expires_at <= now:
        verification.is_used = True
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "O código expirou. Solicite "
                "um novo código."
            ),
        )

    if verification.attempts >= MAX_ATTEMPTS:
        verification.is_used = True
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Número máximo de tentativas "
                "atingido. Solicite um novo código."
            ),
        )

    received_hash = hash_verification_code(
        code
    )

    is_valid = hmac.compare_digest(
        received_hash,
        verification.code_hash,
    )

    if not is_valid:
        verification.attempts += 1
        db.commit()

        remaining_attempts = max(
            0,
            MAX_ATTEMPTS
            - verification.attempts,
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Código inválido. "
                f"Restam {remaining_attempts} "
                "tentativas."
            ),
        )

    verification.is_used = True
    user.is_email_verified = True

    db.commit()
    db.refresh(user)


def get_resend_wait_seconds(
    verification:
        Optional[EmailVerificationCode],
) -> int:
    if verification is None:
        return 0

    elapsed = (
        utc_now()
        - verification.last_sent_at
    ).total_seconds()

    remaining = RESEND_SECONDS - int(elapsed)

    return max(
        0,
        remaining,
    )


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

    code = create_verification_code(
        db=db,
        user=user,
    )

    return code, RESEND_SECONDS