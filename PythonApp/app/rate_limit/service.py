import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as app_models
from app.auth.dependencies import get_current_user
from app.database import get_db


# --- limites por escopo (env-overridable, mesmo padrão de
# app/auth/verification_service.py) ---

LOGIN_MAX = int(os.getenv("RATE_LIMIT_LOGIN_MAX", "10"))
LOGIN_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "60")
)

REGISTER_MAX = int(os.getenv("RATE_LIMIT_REGISTER_MAX", "3"))
REGISTER_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_REGISTER_WINDOW_SECONDS", "60")
)

# IPs que não passam pelo rate limit por IP (ex.: máquina de quem está
# testando o cadastro manualmente). Lista separada por vírgula.
EXEMPT_IPS = {
    ip.strip()
    for ip in os.getenv("RATE_LIMIT_EXEMPT_IPS", "").split(",")
    if ip.strip()
}

VERIFY_EMAIL_MAX = int(os.getenv("RATE_LIMIT_VERIFY_EMAIL_MAX", "10"))
VERIFY_EMAIL_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_VERIFY_EMAIL_WINDOW_SECONDS", "60")
)

RESEND_VERIFICATION_MAX = int(
    os.getenv("RATE_LIMIT_RESEND_VERIFICATION_MAX", "5")
)
RESEND_VERIFICATION_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_RESEND_VERIFICATION_WINDOW_SECONDS", "60")
)

VIDEO_UPLOAD_MAX = int(os.getenv("RATE_LIMIT_VIDEO_UPLOAD_MAX", "10"))
VIDEO_UPLOAD_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_VIDEO_UPLOAD_WINDOW_SECONDS", "3600")
)

THUMBNAIL_UPDATE_MAX = int(
    os.getenv("RATE_LIMIT_THUMBNAIL_UPDATE_MAX", "10")
)
THUMBNAIL_UPDATE_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_THUMBNAIL_UPDATE_WINDOW_SECONDS", "3600")
)

OPENAI_ENDPOINT_MAX = int(os.getenv("RATE_LIMIT_OPENAI_MAX", "20"))
OPENAI_ENDPOINT_WINDOW_SECONDS = int(
    os.getenv("RATE_LIMIT_OPENAI_WINDOW_SECONDS", "3600")
)


_UPSERT_SQL = text(
    """
    INSERT INTO rate_limit_buckets (key, window_start, count)
    VALUES (:key, :now, 1)
    ON CONFLICT (key) DO UPDATE SET
        count = CASE
            WHEN rate_limit_buckets.window_start
                <= :now - make_interval(secs => :window_seconds)
            THEN 1
            ELSE rate_limit_buckets.count + 1
        END,
        window_start = CASE
            WHEN rate_limit_buckets.window_start
                <= :now - make_interval(secs => :window_seconds)
            THEN :now
            ELSE rate_limit_buckets.window_start
        END
    RETURNING count, window_start
    """
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


def increment_and_get_count(
    db: Session,
    key: str,
    window_seconds: int,
) -> tuple[int, datetime]:
    """Incrementa o contador de `key` numa janela fixa de
    `window_seconds` e devolve (count, window_start) — sem levantar
    429, quem decide o que fazer com a contagem é o chamador (usado
    tanto por check_rate_limit quanto pelo gate de créditos de IA em
    app.credits.service, que passa a agir só depois desse limite
    gratuito estourar).

    O upsert é atômico no Postgres (o lock da linha em conflito
    serializa concorrência entre instâncias/processos), então não há
    condição de corrida entre requisições concorrentes usando a mesma
    chave.
    """

    now = _now()

    row = db.execute(
        _UPSERT_SQL,
        {
            "key": key,
            "now": now,
            "window_seconds": window_seconds,
        },
    ).first()

    db.commit()

    return row.count, row.window_start


def check_rate_limit(
    db: Session,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Levanta 429 se `key` já atingiu `limit` requisições na janela
    atual (ver increment_and_get_count)."""

    count, window_start = increment_and_get_count(
        db, key, window_seconds
    )

    now = _now()

    if count > limit:
        retry_after = max(
            1,
            int(
                window_seconds
                - (now - window_start).total_seconds()
            ),
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Muitas requisições. Tente novamente em instantes."
            ),
            headers={"Retry-After": str(retry_after)},
        )


def ip_rate_limiter(scope: str, limit: int, window_seconds: int):
    """Dependency factory: limita por escopo + IP do cliente.

    Usado em endpoints que não exigem autenticação (login, registro,
    verificação de e-mail e os endpoints que chamam a OpenAI, que hoje
    são todos públicos).
    """

    def _dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> None:
        client_ip = _client_ip(request)

        if client_ip in EXEMPT_IPS:
            return

        key = f"{scope}:ip:{client_ip}"
        check_rate_limit(db, key, limit, window_seconds)

    return _dependency


def user_rate_limiter(scope: str, limit: int, window_seconds: int):
    """Dependency factory: limita por escopo + usuário autenticado.

    Usado em endpoints que já exigem autenticação (ex.: upload de
    vídeo). Depende de get_current_user, então o FastAPI reaproveita o
    usuário já resolvido caso a rota também declare esse dependency.
    """

    def _dependency(
        db: Session = Depends(get_db),
        current_user: app_models.User = Depends(get_current_user),
    ) -> None:
        key = f"{scope}:user:{current_user.id}"
        check_rate_limit(db, key, limit, window_seconds)

    return _dependency
