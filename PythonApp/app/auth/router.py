# auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from fastapi import Response

from app import models # Importa schemas e models do nível acima
from .dependencies import verify_password, get_password_hash 

from app import schemas as app_schemas
from . import schemas as auth_schemas

from app.auth.refresh_token_service import (
    create_refresh_token,
    rotate_refresh_token,
)

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
    Body,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.email_service import (
    send_verification_email,
)
from app.auth.schemas import (
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

from app.schemas import (
    AuthenticationLoginResponse,
)
from app.auth.token_service import (
    create_access_token,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES
)

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
    response_model=auth_schemas.AuthenticationRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    request: auth_schemas.AuthenticationRegisterRequest,
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

        return auth_schemas.AuthenticationRegisterResponse(
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

    return auth_schemas.AuthenticationRegisterResponse(
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
    response_model=auth_schemas.AuthenticationLoginResponse,
)
def login_user(
    user_credentials: app_schemas.UserLogin = Body(...),
    db: Session = Depends(get_db),
):
    print(
        "🟢 ENTROU NO ENDPOINT DE LOGIN",
        flush=True,
    )

    normalized_identifier = (
        user_credentials.username
        .strip()
        .lower()
    )

    print(
        "🔎 Antes de consultar usuário",
        flush=True,
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

    print(
        "✅ Consulta do usuário terminou",
        flush=True,
    )

    if db_user is None:
        print(
            "❌ Usuário não encontrado",
            flush=True,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos.",
        )

    print(
        "🔐 Antes de verificar senha",
        flush=True,
    )

    password_is_valid = verify_password(
        user_credentials.password,
        db_user.hashed_password,
    )

    print(
        "✅ Verificação de senha terminou",
        flush=True,
    )

    if not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos.",
        )

    if not db_user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_not_verified",
                "message": """
                Confirme seu e-mail antes de fazer login.
                """,
                "email": db_user.email,
            },
        )

    print(
        "🎟️ Antes de criar token",
        flush=True,
    )

    access_token = create_access_token(
        db_user.id
    )

    refresh_token = create_refresh_token(
        db=db,
        user_id=db_user.id,
    )

    db.commit()

    print(
        "✅ Token criado",
        flush=True,
    )

    response = (
        auth_schemas
    .AuthenticationLoginResponse(
        id=db_user.id,
        email=db_user.email,
        username=db_user.username,
        is_active=db_user.is_active,
        is_email_verified=
            db_user.is_email_verified,
        created_at=
            db_user.created_at,
        updated_at=
            db_user.updated_at,
        access_token=
            access_token,
        refresh_token=
            refresh_token,
        token_type=
            "bearer",
        expires_in=
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES
            * 60,
        )
    )

    print(
        "🏁 LOGIN FINALIZADO",
        flush=True,
    )

    print(
        "🔑 Refresh token criado:",
        bool(refresh_token),
        flush=True,
    )

    print(
        "📦 RESPONSE LOGIN:",
        response.model_dump(),
        flush=True,
    )

    return response

@router.get("/{user_id}", response_model=auth_schemas.AuthenticationUserResponse)
def get_user(user_id: str, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return db_user

@router.put("/{user_id}", response_model=auth_schemas.AuthenticationUserResponse)
def update_user(user_id: str, updated_user: app_schemas.UserUpdate, db: Session = Depends(get_db)):
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

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    try:
        db.delete(user)
        db.commit()

    except IntegrityError as error:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Não foi possível excluir o usuário "
                "porque ainda existem dados vinculados "
                "a essa conta."
            ),
        ) from error

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível excluir o usuário.",
        ) from error

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )

@router.post(
    "/refresh",
    response_model=
        auth_schemas.TokenRefreshResponse,
)
def refresh_access_token(
    payload:
        auth_schemas.RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    user_id, new_refresh_token = (
        rotate_refresh_token(
            db=db,
            raw_token=
                payload.refresh_token,
        )
    )

    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id
        )
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Usuário não encontrado.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=
                status.HTTP_403_FORBIDDEN,
            detail=
                "Usuário desativado.",
        )

    access_token = create_access_token(
        user.id
    )

    return (
        auth_schemas
        .TokenRefreshResponse(
            access_token=
                access_token,
            refresh_token=
                new_refresh_token,
            token_type=
                "bearer",
            expires_in=(
                JWT_ACCESS_TOKEN_EXPIRE_MINUTES
                * 60
            ),
        )
    )