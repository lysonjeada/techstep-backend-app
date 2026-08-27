# auth/router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from fastapi import Response

from app import models # Importa schemas e models do nível acima
from .dependencies import verify_password, get_password_hash, get_current_user

from app import schemas as app_schemas
from . import schemas as auth_schemas

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.auth.refresh_token_service import (
    create_refresh_token,
    revoke_all_refresh_tokens_for_user,
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
    send_password_reset_email,
    send_verification_email,
)
from app.auth.schemas import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
    VerifyPasswordResetCodeRequest,
    VerifyPasswordResetCodeResponse,
)
from app.auth.verification_service import (
    create_resend_code,
    create_verification_code,
    validate_verification_code,
)
from app.auth import password_reset_service
from app.database import get_db
from app.models import User
from app.observability import logger

from app.schemas import (
    AuthenticationLoginResponse,
)
from app.auth.token_service import (
    create_access_token,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.rate_limit.service import (
    FORGOT_PASSWORD_EMAIL_MAX,
    FORGOT_PASSWORD_EMAIL_WINDOW_SECONDS,
    FORGOT_PASSWORD_MAX,
    FORGOT_PASSWORD_WINDOW_SECONDS,
    LOGIN_MAX,
    LOGIN_WINDOW_SECONDS,
    REGISTER_MAX,
    REGISTER_WINDOW_SECONDS,
    RESEND_VERIFICATION_MAX,
    RESEND_VERIFICATION_WINDOW_SECONDS,
    RESET_PASSWORD_MAX,
    RESET_PASSWORD_WINDOW_SECONDS,
    VERIFY_EMAIL_MAX,
    VERIFY_EMAIL_WINDOW_SECONDS,
    VERIFY_RESET_CODE_MAX,
    VERIFY_RESET_CODE_WINDOW_SECONDS,
    check_rate_limit,
    ip_rate_limiter,
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
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "register", REGISTER_MAX, REGISTER_WINDOW_SECONDS
        )
    ),
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
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "verify-email",
            VERIFY_EMAIL_MAX,
            VERIFY_EMAIL_WINDOW_SECONDS,
        )
    ),
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
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "resend-verification",
            RESEND_VERIFICATION_MAX,
            RESEND_VERIFICATION_WINDOW_SECONDS,
        )
    ),
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
    "/forgot-password",
    response_model=ForgotPasswordResponse,
)
def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "forgot-password",
            FORGOT_PASSWORD_MAX,
            FORGOT_PASSWORD_WINDOW_SECONDS,
        )
    ),
):
    normalized_email = (
        request.email.strip().lower()
    )

    # Limite adicional por e-mail (além do IP acima) — não revela
    # existência: a mesma checagem roda com ou sem conta cadastrada.
    check_rate_limit(
        db,
        f"forgot-password:email:{normalized_email}",
        FORGOT_PASSWORD_EMAIL_MAX,
        FORGOT_PASSWORD_EMAIL_WINDOW_SECONDS,
    )

    # Resposta sempre idêntica (mensagem + status 200), exista ou não
    # o e-mail — protege contra enumeração de contas cadastradas.
    generic_message = (
        "Se o e-mail estiver cadastrado, enviaremos um código "
        "para redefinição da senha."
    )

    user = (
        db.query(User)
        .filter(User.email == normalized_email)
        .first()
    )

    if user is not None and user.is_active:
        code = None

        try:
            code, _ = password_reset_service.create_resend_code(
                db=db,
                user=user,
            )
        except HTTPException as error:
            # Já existe um código recente (cooldown): não revela isso
            # ao chamador, só evita mandar outro e-mail agora.
            if (
                error.status_code
                != status.HTTP_429_TOO_MANY_REQUESTS
            ):
                raise

        if code is not None:
            background_tasks.add_task(
                send_password_reset_email,
                user.email,
                user.username,
                code,
            )

        logger.info(
            "password_reset_requested",
            extra={"event": "password_reset_requested"},
        )

    return ForgotPasswordResponse(
        message=generic_message
    )


@router.post(
    "/verify-reset-code",
    response_model=VerifyPasswordResetCodeResponse,
)
def verify_reset_code(
    request: VerifyPasswordResetCodeRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "verify-reset-code",
            VERIFY_RESET_CODE_MAX,
            VERIFY_RESET_CODE_WINDOW_SECONDS,
        )
    ),
):
    normalized_email = (
        request.email.strip().lower()
    )

    user = (
        db.query(User)
        .filter(User.email == normalized_email)
        .first()
    )

    if user is None:
        # Mesma mensagem/status de "código inválido" — não revela se
        # o e-mail existe.
        logger.info(
            "password_reset_code_verification_failed",
            extra={
                "event":
                    "password_reset_code_verification_failed"
            },
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_reset_service.INVALID_CODE_MESSAGE,
        )

    try:
        reset_token = (
            password_reset_service
            .validate_reset_code_and_issue_token(
                db=db,
                user=user,
                code=request.code,
            )
        )
    except HTTPException:
        logger.info(
            "password_reset_code_verification_failed",
            extra={
                "event":
                    "password_reset_code_verification_failed"
            },
        )
        raise

    logger.info(
        "password_reset_code_verified",
        extra={"event": "password_reset_code_verified"},
    )

    return VerifyPasswordResetCodeResponse(
        reset_token=reset_token
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
)
def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "reset-password",
            RESET_PASSWORD_MAX,
            RESET_PASSWORD_WINDOW_SECONDS,
        )
    ),
):
    try:
        user = (
            password_reset_service
            .consume_reset_token(
                db=db,
                raw_token=request.reset_token,
            )
        )

        user.hashed_password = hash_password(
            request.new_password
        )

        revoke_all_refresh_tokens_for_user(
            db,
            user.id,
        )

        password_reset_service.invalidate_active_reset_artifacts_for_user(
            db=db,
            user_id=user.id,
        )

        db.commit()

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()

        logger.exception(
            "password_reset_failed",
            extra={"event": "password_reset_failed"},
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Não foi possível redefinir a senha. "
                "Tente novamente."
            ),
        )

    logger.info(
        "password_reset_completed",
        extra={"event": "password_reset_completed"},
    )

    return ResetPasswordResponse(
        message="Senha redefinida com sucesso."
    )


@router.post(
    "/login/",
    response_model=auth_schemas.AuthenticationLoginResponse,
)
def login_user(
    user_credentials: app_schemas.UserLogin = Body(...),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(
        ip_rate_limiter(
            "login", LOGIN_MAX, LOGIN_WINDOW_SECONDS
        )
    ),
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

def _apply_profile_update(
    db: Session,
    db_user: models.User,
    updated_user: app_schemas.UserUpdate,
) -> models.User:
    if updated_user.password is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Para alterar a senha, use "
                "PUT /users/me/password."
            ),
        )

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

    db.commit()
    db.refresh(db_user)
    return db_user


def _delete_user(
    db: Session,
    user: models.User,
) -> Response:
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


@router.get(
    "/me",
    response_model=auth_schemas.AuthenticationUserResponse,
)
def get_current_user_profile(
    current_user: models.User = Depends(get_current_user),
):
    return current_user


@router.put(
    "/me",
    response_model=auth_schemas.AuthenticationUserResponse,
)
def update_current_user_profile(
    updated_user: app_schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _apply_profile_update(
        db,
        current_user,
        updated_user,
    )


@router.put(
    "/me/password",
    response_model=auth_schemas.PasswordUpdateResponse,
)
def update_current_user_password(
    payload: auth_schemas.UserPasswordUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(
        payload.current_password,
        current_user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha atual incorreta.",
        )

    current_user.hashed_password = hash_password(
        payload.new_password
    )

    revoke_all_refresh_tokens_for_user(
        db,
        current_user.id,
    )

    db.commit()

    return auth_schemas.PasswordUpdateResponse(
        message="Senha atualizada com sucesso."
    )


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_current_user(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    return _delete_user(db, current_user)


@router.get("/{user_id}", response_model=auth_schemas.AuthenticationUserResponse)
def get_user(
    user_id: UUID,
    current_user: models.User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    return current_user

@router.put("/{user_id}", response_model=auth_schemas.AuthenticationUserResponse)
def update_user(
    user_id: UUID,
    updated_user: app_schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    return _apply_profile_update(db, current_user, updated_user)

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user(
    user_id: UUID,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    return _delete_user(db, current_user)

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