# auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app import schemas, models # Importa schemas e models do nível acima
from .dependencies import get_db, verify_password, get_password_hash 

from app.auth.security import (
    hash_password,
    verify_password,
)

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.email_service import (
    send_verification_email,
)
from app.auth.schemas import (
    AuthenticationRegisterRequest,
    AuthenticationRegisterResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.auth.verification_service import (
    create_resend_code,
    create_verification_code,
    validate_verification_code,
)
from app.database import get_db
from app.models import User


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

router = APIRouter(
    prefix="/users",
    tags=["Users and Authentication"]
)

@router.post(
    "/register",
    response_model=AuthenticationRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    request: AuthenticationRegisterRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    normalized_email = (
        request.email
        .strip()
        .lower()
    )

    normalized_username = (
        request.username
        .strip()
    )

    existing_email_user = (
        db.query(models.User)
        .filter(
            models.User.email
            == normalized_email
        )
        .first()
    )

    existing_username_user = (
        db.query(models.User)
        .filter(
            models.User.username
            == normalized_username
        )
        .first()
    )

    # O e-mail já existe e já foi confirmado.
    if (
        existing_email_user is not None
        and existing_email_user.is_email_verified
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail já está cadastrado.",
        )

    # O username pertence a outro cadastro.
    if (
        existing_username_user is not None
        and (
            existing_email_user is None
            or existing_username_user.id
            != existing_email_user.id
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este username já está em uso.",
        )

    # Existe um cadastro pendente para este e-mail.
    if existing_email_user is not None:
        user = existing_email_user

        try:
            code, retry_after = create_resend_code(
                db=db,
                user=user,
            )

            background_tasks.add_task(
                send_verification_email,
                user.email,
                user.username,
                code,
            )

            message = (
                "Seu cadastro ainda está pendente. "
                "Enviamos um novo código para o seu e-mail."
            )

        except HTTPException as error:
            # Caso ainda esteja dentro do intervalo de reenvio,
            # não bloqueamos a navegação para a confirmação.
            if (
                error.status_code
                == status.HTTP_429_TOO_MANY_REQUESTS
            ):
                retry_after = int(
                    error.headers.get(
                        "Retry-After",
                        "60",
                    )
                )

                message = (
                    "Seu cadastro ainda está pendente. "
                    "Use o código enviado anteriormente "
                    "ou aguarde para solicitar outro."
                )
            else:
                raise

        return AuthenticationRegisterResponse(
            user_id=user.id,
            email=user.email,
            verification_required=True,
            message=message,
            retry_after_seconds=retry_after,
        )

    # Novo cadastro.
    user = models.User(
        username=normalized_username,
        email=normalized_email,
        hashed_password=hash_password(
            request.password
        ),
        is_email_verified=False,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    verification_code = create_verification_code(
        db=db,
        user=user,
    )

    background_tasks.add_task(
        send_verification_email,
        user.email,
        user.username,
        verification_code,
    )

    return AuthenticationRegisterResponse(
        user_id=user.id,
        email=user.email,
        verification_required=True,
        message=(
            "Cadastro realizado. "
            "Enviamos um código para o seu e-mail."
        ),
        retry_after_seconds=60,
    )

@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
)
def verify_email(
    request: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    normalized_email = (
        request.email
        .strip()
        .lower()
    )

    user = (
        db.query(User)
        .filter(
            User.email
            == normalized_email
        )
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    if user.is_email_verified:
        return VerifyEmailResponse(
            verified=True,
            message=(
                "Este e-mail já foi verificado."
            ),
        )

    validate_verification_code(
        db=db,
        user=user,
        code=request.code,
    )

    return VerifyEmailResponse(
        verified=True,
        message=(
            "E-mail verificado com sucesso."
        ),
    )

@router.post(
    "/resend-verification",
    response_model=
        ResendVerificationResponse,
)
def resend_verification_code(
    request: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    normalized_email = (
        request.email
        .strip()
        .lower()
    )

    user = (
        db.query(User)
        .filter(
            User.email
            == normalized_email
        )
        .first()
    )

    # Resposta genérica também evita revelar
    # quais e-mails existem no sistema.
    if user is None:
        return ResendVerificationResponse(
            message=(
                "Caso exista uma conta pendente, "
                "um novo código será enviado."
            ),
            retry_after_seconds=60,
        )

    if user.is_email_verified:
        return ResendVerificationResponse(
            message=(
                "Este e-mail já foi verificado."
            ),
            retry_after_seconds=60,
        )

    code, retry_after = (
        create_resend_code(
            db=db,
            user=user,
        )
    )

    background_tasks.add_task(
        send_verification_email,
        user.email,
        user.username,
        code,
    )

    return ResendVerificationResponse(
        message=(
            "Um novo código foi enviado."
        ),
        retry_after_seconds=retry_after,
    )

@router.post(
    "/login/",
    response_model=schemas.UserOut,
)
def login_user(
    user_credentials: schemas.UserLogin,
    db: Session = Depends(get_db),
):
    normalized_identifier = (
        user_credentials.username
        .strip()
        .lower()
    )

    db_user = (
        db.query(models.User)
        .filter(
            or_(
                models.User.username
                == user_credentials.username.strip(),
                models.User.email
                == normalized_identifier,
            )
        )
        .first()
    )

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos.",
        )

    if not verify_password(
        user_credentials.password,
        db_user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos.",
        )

    if not db_user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_not_verified",
                "message": (
                    "Confirme seu e-mail antes "
                    "de fazer login."
                ),
                "email": db_user.email,
            },
        )

    return db_user

@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return db_user

@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: str, updated_user: schemas.UserUpdate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    if updated_user.email is not None and updated_user.email != db_user.email:
        existing_email_user = db.query(models.User).filter(models.User.email == updated_user.email).first()
        if existing_email_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo email já está em uso")
        db_user.email = updated_user.email

    if updated_user.username is not None and updated_user.username != db_user.username:
        existing_username_user = db.query(models.User).filter(models.User.username == updated_user.username).first()
        if existing_username_user:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Novo nome de usuário já está em uso")
        db_user.username = updated_user.username

    if updated_user.password is not None:
        db_user.hashed_password = hash_password(updated_user.password)

    db.commit()
    db.refresh(db_user)
    return db_user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    
    db.delete(db_user)
    db.commit()
    return