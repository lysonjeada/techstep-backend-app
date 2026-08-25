import hashlib
import html
import math
import os
import secrets

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from fastapi.responses import (
    FileResponse,
    HTMLResponse,
)

from sqlalchemy.orm import Session

from app import models as app_models
from app.auth.dependencies import (
    get_current_user,
)
from app.database import get_db

from app.rate_limit.service import (
    THUMBNAIL_UPDATE_MAX,
    THUMBNAIL_UPDATE_WINDOW_SECONDS,
    VIDEO_UPLOAD_MAX,
    VIDEO_UPLOAD_WINDOW_SECONDS,
    user_rate_limiter,
)

from app.uploads.validation import (
    is_allowed_image_content,
    is_allowed_video_content,
    read_upload_with_limit,
)

from . import (
    models,
    schemas,
)

from .email_service import (
    send_thumbnail_review_email,
    send_upload_review_email,
    send_video_review_email,
)

from app.observability import (
    logger,
)


router = APIRouter(
    prefix="/videos",
    tags=["Videos"],
)


UPLOAD_DIR = Path(
    os.getenv(
        "VIDEO_UPLOAD_DIR",
        "uploads/videos",
    )
)

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


PUBLIC_API_URL = os.getenv(
    "PUBLIC_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


MAX_VIDEO_SIZE = (
    int(
        os.getenv(
            "VIDEO_MAX_SIZE_MB",
            "200",
        )
    )
    * 1024
    * 1024
)


VIDEO_EXTENSION_BY_CONTENT_TYPE = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-m4v": ".m4v",
    "video/webm": ".webm",
}

ALLOWED_TYPES = set(VIDEO_EXTENSION_BY_CONTENT_TYPE)


# --- Thumbnail ---
#
# Fica numa pasta separada da dos vídeos (arquivos pequenos, sem
# relação com o streaming/limite de tamanho de vídeo).

THUMBNAIL_UPLOAD_DIR = Path(
    os.getenv(
        "THUMBNAIL_UPLOAD_DIR",
        "uploads/thumbnails",
    )
)

THUMBNAIL_UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

THUMBNAIL_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

MAX_THUMBNAIL_SIZE = (
    int(
        os.getenv(
            "THUMBNAIL_MAX_SIZE_MB",
            "5",
        )
    )
    * 1024
    * 1024
)


def hash_review_token(
    token: str,
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def next_resend_allowed_at(
    video: models.Video,
) -> datetime | None:
    if (
        video.status != "pending"
        or video.review_notification_sent_at
        is None
    ):
        return None

    return (
        video.review_notification_sent_at
        + timedelta(days=1)
    )


def thumbnail_next_resend_allowed_at(
    video: models.Video,
) -> datetime | None:
    if (
        not video.pending_thumbnail_file_name
        or video.thumbnail_review_notification_sent_at
        is None
    ):
        return None

    return (
        video.thumbnail_review_notification_sent_at
        + timedelta(days=1)
    )


def serialize_video(
    video: models.Video,
) -> schemas.VideoOut:
    stream_path = None

    if video.status == "approved":
        stream_path = (
            f"/videos/{video.id}/file"
        )

    thumbnail_url = None

    if video.thumbnail_file_name:
        thumbnail_url = (
            f"/videos/{video.id}/thumbnail"
        )

    if video.pending_thumbnail_file_name:
        thumbnail_status = "pending"
    elif video.thumbnail_source == "custom":
        thumbnail_status = "approved"
    else:
        thumbnail_status = "auto"

    return schemas.VideoOut(
        id=video.id,
        user_id=video.user_id,
        title=video.title,
        description=video.description,
        status=video.status,
        rejection_reason=
            video.rejection_reason,
        created_at=video.created_at,
        reviewed_at=video.reviewed_at,
        stream_path=stream_path,
        next_resend_allowed_at=
            next_resend_allowed_at(video),
        thumbnail_url=thumbnail_url,
        thumbnail_status=thumbnail_status,
        thumbnail_rejection_reason=
            video.thumbnail_rejection_reason,
        thumbnail_next_resend_allowed_at=
            thumbnail_next_resend_allowed_at(video),
    )


def validate_review_token(
    video: models.Video,
    token: str,
):
    if (
        hash_review_token(token)
        != video.review_token_hash
    ):
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Token de revisão inválido.",
        )

    now = datetime.now(
        timezone.utc
    )

    if (
        video.review_token_expires_at
        < now
    ):
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Token de revisão expirado.",
        )


def validate_thumbnail_review_token(
    video: models.Video,
    token: str,
):
    if (
        not video.thumbnail_review_token_hash
        or hash_review_token(token)
        != video.thumbnail_review_token_hash
    ):
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Token de revisão inválido.",
        )

    now = datetime.now(
        timezone.utc
    )

    if (
        video.thumbnail_review_token_expires_at
        is None
        or video.thumbnail_review_token_expires_at
        < now
    ):
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,
            detail=
                "Token de revisão expirado.",
        )


def _send_email_task(
    send_fn,
    **kwargs,
) -> None:
    """`BackgroundTasks` roda as tarefas de uma requisição em
    sequência e para na primeira que lançar exceção (starlette não
    isola cada uma) — sem isso, uma falha ao enviar o e-mail de
    revisão do vídeo derrubaria silenciosamente o envio do e-mail de
    revisão da thumbnail agendado na mesma requisição, e vice-versa."""

    try:
        send_fn(**kwargs)

    except Exception:
        logger.exception(
            "failed to send review email",
            extra={
                "event":
                    "review_email_send_failed",
                "emailFunction":
                    send_fn.__name__,
            },
        )


def _delete_thumbnail_file(
    file_name: str | None,
) -> None:
    if not file_name:
        return

    path = THUMBNAIL_UPLOAD_DIR / file_name

    if not path.exists():
        return

    try:
        path.unlink()

    except OSError:
        logger.exception(
            "failed to remove thumbnail file",
            extra={
                "event":
                    "thumbnail_file_removal_failed",
                "fileName": file_name,
            },
        )


async def _save_uploaded_thumbnail(
    upload: UploadFile,
    video_id: UUID,
    suffix_hint: str,
) -> str:
    """Valida (tamanho + magic bytes) e salva uma imagem de thumbnail
    em THUMBNAIL_UPLOAD_DIR, devolvendo o nome do arquivo salvo (nunca
    derivado do filename/Content-Type crus do cliente, mesma regra de
    upload_video)."""

    if (
        upload.content_type
        not in THUMBNAIL_EXTENSION_BY_CONTENT_TYPE
    ):
        raise HTTPException(
            status_code=
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=
                "Formato de imagem não suportado para a thumbnail.",
        )

    content = await read_upload_with_limit(
        upload,
        MAX_THUMBNAIL_SIZE,
        detail=
            "A imagem da thumbnail excede o tamanho máximo permitido.",
    )

    await upload.close()

    if not content or not is_allowed_image_content(content):
        raise HTTPException(
            status_code=
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "O conteúdo enviado não corresponde "
                "a uma imagem válida."
            ),
        )

    suffix = THUMBNAIL_EXTENSION_BY_CONTENT_TYPE[
        upload.content_type
    ]

    saved_file_name = (
        f"{video_id}_{suffix_hint}_"
        f"{secrets.token_hex(4)}{suffix}"
    )

    (
        THUMBNAIL_UPLOAD_DIR
        / saved_file_name
    ).write_bytes(content)

    return saved_file_name


# MARK: Upload


@router.post(
    "/",
    response_model=schemas.VideoOut,
    status_code=
        status.HTTP_201_CREATED,
)
async def upload_video(
    background_tasks: BackgroundTasks,

    title: str = Form(...),

    description: str | None = Form(
        default=None
    ),

    file: UploadFile = File(...),

    # Gerada no app a partir do 1º segundo do vídeo — sempre enviada
    # pelo cliente quando o usuário não escolhe uma imagem própria, e
    # também como fallback mesmo quando `thumbnail` é enviado (garante
    # que sempre exista uma imagem exibível enquanto a customizada
    # ainda não foi aprovada). Não passa por revisão: é só um frame do
    # próprio vídeo, que já vai passar por análise.
    auto_thumbnail: UploadFile | None = File(
        default=None
    ),

    # Imagem escolhida pelo usuário para a thumbnail — opcional, fica
    # pendente até ser aprovada por e-mail.
    thumbnail: UploadFile | None = File(
        default=None
    ),

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),

    _rate_limit: None = Depends(
        user_rate_limiter(
            "video-upload",
            VIDEO_UPLOAD_MAX,
            VIDEO_UPLOAD_WINDOW_SECONDS,
        )
    ),
):
    normalized_title = title.strip()

    if not normalized_title:
        raise HTTPException(
            status_code=
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o título.",
        )

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=
                "Formato de vídeo não suportado.",
        )

    video_id = UUID(
        bytes=secrets.token_bytes(16)
    )

    # O nome salvo em disco nunca depende do filename enviado pelo
    # cliente: é sempre <uuid gerado no servidor> + extensão vinda de
    # uma tabela fixa indexada pelo Content-Type já validado acima.
    # Isso fecha qualquer superfície de path traversal via nome de
    # arquivo.
    suffix = VIDEO_EXTENSION_BY_CONTENT_TYPE[
        file.content_type
    ]

    saved_file_name = (
        f"{video_id}{suffix}"
    )

    file_path = (
        UPLOAD_DIR
        / saved_file_name
    )

    size = 0
    content_verified = False

    try:
        with file_path.open(
            "wb"
        ) as destination:

            while True:
                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                if not content_verified:
                    # Os primeiros bytes do arquivo (magic bytes) são
                    # a única fonte confiável do formato real — o
                    # Content-Type é só um chute do cliente e pode
                    # mentir.
                    if not is_allowed_video_content(chunk):
                        raise HTTPException(
                            status_code=
                                status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=(
                                "O conteúdo do arquivo não "
                                "corresponde a um vídeo válido."
                            ),
                        )

                    content_verified = True

                size += len(chunk)

                if size > MAX_VIDEO_SIZE:
                    raise HTTPException(
                        status_code=
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=
                            "O vídeo excede o tamanho máximo permitido.",
                    )

                destination.write(
                    chunk
                )

        if not content_verified:
            raise HTTPException(
                status_code=
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O arquivo de vídeo está vazio.",
            )

    except Exception:
        if file_path.exists():
            file_path.unlink()

        raise

    finally:
        await file.close()

    thumbnail_file_name: str | None = None
    pending_thumbnail_file_name: str | None = None

    try:
        if auto_thumbnail is not None:
            thumbnail_file_name = (
                await _save_uploaded_thumbnail(
                    auto_thumbnail,
                    video_id,
                    "auto",
                )
            )

        if thumbnail is not None:
            pending_thumbnail_file_name = (
                await _save_uploaded_thumbnail(
                    thumbnail,
                    video_id,
                    "pending",
                )
            )

    except Exception:
        _delete_thumbnail_file(
            thumbnail_file_name
        )

        if file_path.exists():
            file_path.unlink()

        raise

    thumbnail_review_token = (
        secrets.token_urlsafe(32)
        if pending_thumbnail_file_name
        else None
    )

    review_token = (
        secrets.token_urlsafe(32)
    )

    now = datetime.now(timezone.utc)

    video = models.Video(
        id=video_id,
        user_id=current_user.id,

        title=normalized_title,

        description=(
            description.strip()
            if description
            else None
        ),

        file_name=
            saved_file_name,

        original_file_name=
            file.filename
            or saved_file_name,

        content_type=
            file.content_type,

        size_bytes=size,

        status="pending",

        review_token_hash=
            hash_review_token(
                review_token
            ),

        review_token_expires_at=(
            datetime.now(
                timezone.utc
            )
            + timedelta(days=7)
        ),

        review_notification_sent_at=(
            datetime.now(
                timezone.utc
            )
        ),

        thumbnail_file_name=
            thumbnail_file_name,

        thumbnail_source="auto",

        pending_thumbnail_file_name=
            pending_thumbnail_file_name,

        thumbnail_review_token_hash=(
            hash_review_token(
                thumbnail_review_token
            )
            if thumbnail_review_token
            else None
        ),

        thumbnail_review_token_expires_at=(
            now + timedelta(days=7)
            if thumbnail_review_token
            else None
        ),

        thumbnail_review_notification_sent_at=(
            now
            if thumbnail_review_token
            else None
        ),
    )

    try:
        db.add(video)
        db.commit()
        db.refresh(video)

    except Exception:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        _delete_thumbnail_file(
            thumbnail_file_name
        )

        _delete_thumbnail_file(
            pending_thumbnail_file_name
        )

        raise

    review_url = (
        f"{PUBLIC_API_URL}"
        f"/videos/{video.id}"
        f"/review"
        f"?token={quote(review_token)}"
    )

    thumbnail_review_url = (
        (
            f"{PUBLIC_API_URL}"
            f"/videos/{video.id}"
            f"/thumbnail-review"
            f"?token={quote(thumbnail_review_token)}"
        )
        if thumbnail_review_token
        else None
    )

    # Vídeo e thumbnail (quando enviada junto) vão num único e-mail:
    # duas conexões SMTP quase simultâneas para o mesmo destinatário
    # já mostraram entregar só uma das duas silenciosamente.
    background_tasks.add_task(
        _send_email_task,
        send_upload_review_email,
        title=video.title,
        uploader_email=
            current_user.email,
        review_url=review_url,
        thumbnail_review_url=
            thumbnail_review_url,
    )

    return serialize_video(
        video
    )


# MARK: User videos


@router.get(
    "/mine",
    response_model=
        schemas.VideoPageResponse,
)
def get_my_videos(
    page: int = Query(
        default=1,
        ge=1,
    ),

    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    query = (
        db.query(models.Video)
        .filter(
            models.Video.user_id
            == current_user.id
        )
    )

    total = query.count()

    videos = (
        query
        .order_by(
            models.Video
            .created_at.desc()
        )
        .offset(
            (page - 1)
            * page_size
        )
        .limit(page_size)
        .all()
    )

    total_pages = (
        math.ceil(
            total / page_size
        )
        if total
        else 0
    )

    return schemas.VideoPageResponse(
        items=[
            serialize_video(video)
            for video in videos
        ],

        page=page,
        page_size=page_size,

        total=total,
        total_pages=total_pages,

        has_next=
            page < total_pages,
    )


# MARK: Approved videos - HOME


@router.get(
    "/approved",
    response_model=
        schemas.VideoPageResponse,
)
def get_approved_videos(
    page: int = Query(
        default=1,
        ge=1,
    ),

    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),

    db: Session = Depends(get_db),
):
    query = (
        db.query(models.Video)
        .filter(
            models.Video.status
            == "approved"
        )
    )

    total = query.count()

    videos = (
        query
        .order_by(
            models.Video
            .created_at.desc()
        )
        .offset(
            (page - 1)
            * page_size
        )
        .limit(page_size)
        .all()
    )

    total_pages = (
        math.ceil(
            total / page_size
        )
        if total
        else 0
    )

    return schemas.VideoPageResponse(
        items=[
            serialize_video(video)
            for video in videos
        ],

        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=
            page < total_pages,
    )


# MARK: Delete


@router.delete(
    "/{video_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_video(
    video_id: UUID,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo não encontrado.",
        )

    if (
        video.user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail=
                "Você não pode excluir este vídeo.",
        )

    file_path = (
        UPLOAD_DIR
        / video.file_name
    )

    thumbnail_file_name = (
        video.thumbnail_file_name
    )

    pending_thumbnail_file_name = (
        video.pending_thumbnail_file_name
    )

    db.delete(video)
    db.commit()

    if file_path.exists():
        try:
            file_path.unlink()

        except OSError:
            logger.exception(
                "failed to remove video file after deletion",
                extra={
                    "event":
                        "video_file_removal_failed",
                    "videoId":
                        str(video_id),
                },
            )

    _delete_thumbnail_file(
        thumbnail_file_name
    )

    _delete_thumbnail_file(
        pending_thumbnail_file_name
    )

    logger.info(
        "video deleted",
        extra={
            "event":
                "video_deleted",
            "videoId":
                str(video_id),
            "userId":
                str(current_user.id),
        },
    )


# MARK: Resend review notification


@router.post(
    "/{video_id}/resend-review",
    response_model=
        schemas.ResendReviewResponse,
)
def resend_review_notification(
    video_id: UUID,

    background_tasks: BackgroundTasks,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo não encontrado.",
        )

    if (
        video.user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail=
                "Você não pode reenviar a notificação deste vídeo.",
        )

    if video.status != "pending":
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "VIDEO_NOT_PENDING",
                "message": (
                    "Só é possível reenviar a notificação "
                    "enquanto o vídeo está em análise."
                ),
            },
        )

    now = datetime.now(timezone.utc)

    if video.review_notification_sent_at is not None:
        allowed_at = (
            video.review_notification_sent_at
            + timedelta(days=1)
        )

        if now < allowed_at:
            logger.info(
                "video review notification resend rejected: too soon",
                extra={
                    "event":
                        "video_review_resend_rejected",
                    "videoId":
                        str(video_id),
                    "userId":
                        str(current_user.id),
                },
            )

            raise HTTPException(
                status_code=429,
                detail={
                    "code":
                        "RESEND_TOO_SOON",
                    "message": (
                        "Você já reenviou a notificação "
                        "hoje. Tente novamente amanhã."
                    ),
                    "next_allowed_at":
                        allowed_at.isoformat(),
                },
                headers={
                    "Retry-After": str(
                        int(
                            (
                                allowed_at
                                - now
                            )
                            .total_seconds()
                        )
                    )
                },
            )

    # O token de revisão anterior é substituído — o link antigo (se
    # ainda não expirado) deixa de funcionar, igual ao que já
    # acontece em approve_video/reject_video após uma decisão.
    review_token = (
        secrets.token_urlsafe(32)
    )

    video.review_token_hash = (
        hash_review_token(
            review_token
        )
    )

    video.review_token_expires_at = (
        now + timedelta(days=7)
    )

    video.review_notification_sent_at = now

    db.commit()
    db.refresh(video)

    review_url = (
        f"{PUBLIC_API_URL}"
        f"/videos/{video.id}"
        f"/review"
        f"?token={quote(review_token)}"
    )

    background_tasks.add_task(
        _send_email_task,
        send_video_review_email,
        title=video.title,
        uploader_email=
            current_user.email,
        review_url=review_url,
    )

    logger.info(
        "video review notification resent",
        extra={
            "event":
                "video_review_resent",
            "videoId":
                str(video_id),
            "userId":
                str(current_user.id),
        },
    )

    return schemas.ResendReviewResponse(
        video=serialize_video(video),
        next_resend_allowed_at=(
            now + timedelta(days=1)
        ),
    )


# MARK: Thumbnail


@router.put(
    "/{video_id}/thumbnail",
    response_model=schemas.VideoOut,
)
async def update_thumbnail(
    video_id: UUID,

    background_tasks: BackgroundTasks,

    thumbnail: UploadFile = File(...),

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),

    _rate_limit: None = Depends(
        user_rate_limiter(
            "thumbnail-update",
            THUMBNAIL_UPDATE_MAX,
            THUMBNAIL_UPDATE_WINDOW_SECONDS,
        )
    ),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo não encontrado.",
        )

    if (
        video.user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Você não pode editar a "
                "thumbnail deste vídeo."
            ),
        )

    new_pending_file_name = (
        await _save_uploaded_thumbnail(
            thumbnail,
            video.id,
            "pending",
        )
    )

    # Uma edição pendente anterior (ainda não revisada) é substituída
    # — o arquivo antigo não fica órfão em disco.
    old_pending_file_name = (
        video.pending_thumbnail_file_name
    )

    review_token = (
        secrets.token_urlsafe(32)
    )

    video.pending_thumbnail_file_name = (
        new_pending_file_name
    )

    video.thumbnail_rejection_reason = None

    video.thumbnail_review_token_hash = (
        hash_review_token(review_token)
    )

    video.thumbnail_review_token_expires_at = (
        datetime.now(timezone.utc)
        + timedelta(days=7)
    )

    video.thumbnail_review_notification_sent_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(video)

    _delete_thumbnail_file(
        old_pending_file_name
    )

    review_url = (
        f"{PUBLIC_API_URL}"
        f"/videos/{video.id}"
        f"/thumbnail-review"
        f"?token={quote(review_token)}"
    )

    background_tasks.add_task(
        _send_email_task,
        send_thumbnail_review_email,
        title=video.title,
        uploader_email=
            current_user.email,
        review_url=review_url,
    )

    return serialize_video(video)


@router.post(
    "/{video_id}/resend-thumbnail-review",
    response_model=
        schemas.ResendThumbnailReviewResponse,
)
def resend_thumbnail_review_notification(
    video_id: UUID,

    background_tasks: BackgroundTasks,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo não encontrado.",
        )

    if (
        video.user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Você não pode reenviar a notificação "
                "desta thumbnail."
            ),
        )

    if not video.pending_thumbnail_file_name:
        raise HTTPException(
            status_code=409,
            detail={
                "code":
                    "THUMBNAIL_NOT_PENDING",
                "message": (
                    "Só é possível reenviar a notificação "
                    "enquanto a thumbnail está em análise."
                ),
            },
        )

    now = datetime.now(timezone.utc)

    if video.thumbnail_review_notification_sent_at is not None:
        allowed_at = (
            video.thumbnail_review_notification_sent_at
            + timedelta(days=1)
        )

        if now < allowed_at:
            raise HTTPException(
                status_code=429,
                detail={
                    "code":
                        "RESEND_TOO_SOON",
                    "message": (
                        "Você já reenviou a notificação "
                        "hoje. Tente novamente amanhã."
                    ),
                    "next_allowed_at":
                        allowed_at.isoformat(),
                },
                headers={
                    "Retry-After": str(
                        int(
                            (
                                allowed_at
                                - now
                            )
                            .total_seconds()
                        )
                    )
                },
            )

    review_token = (
        secrets.token_urlsafe(32)
    )

    video.thumbnail_review_token_hash = (
        hash_review_token(review_token)
    )

    video.thumbnail_review_token_expires_at = (
        now + timedelta(days=7)
    )

    video.thumbnail_review_notification_sent_at = now

    db.commit()
    db.refresh(video)

    review_url = (
        f"{PUBLIC_API_URL}"
        f"/videos/{video.id}"
        f"/thumbnail-review"
        f"?token={quote(review_token)}"
    )

    background_tasks.add_task(
        _send_email_task,
        send_thumbnail_review_email,
        title=video.title,
        uploader_email=
            current_user.email,
        review_url=review_url,
    )

    logger.info(
        "thumbnail review notification resent",
        extra={
            "event":
                "thumbnail_review_resent",
            "videoId":
                str(video_id),
            "userId":
                str(current_user.id),
        },
    )

    return schemas.ResendThumbnailReviewResponse(
        video=serialize_video(video),
        next_resend_allowed_at=(
            now + timedelta(days=1)
        ),
    )


@router.get(
    "/{video_id}/thumbnail",
)
def get_video_thumbnail(
    video_id: UUID,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if (
        video is None
        or not video.thumbnail_file_name
    ):
        raise HTTPException(
            status_code=404,
            detail=
                "Thumbnail indisponível.",
        )

    path = (
        THUMBNAIL_UPLOAD_DIR
        / video.thumbnail_file_name
    )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=
                "Arquivo não encontrado.",
        )

    media_type = (
        "image/png"
        if path.suffix == ".png"
        else "image/jpeg"
    )

    return FileResponse(
        path,
        media_type=media_type,
    )


# MARK: Video details


@router.get(
    "/{video_id}",
    response_model=schemas.VideoOut,
)
def get_video(
    video_id: UUID,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo não encontrado.",
        )

    if (
        video.status != "approved"
        and video.user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail=
                "Você não pode visualizar este vídeo.",
        )

    return serialize_video(
        video
    )


# MARK: Public approved file


@router.get(
    "/{video_id}/file",
)
def get_video_file(
    video_id: UUID,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if (
        video is None
        or video.status
        != "approved"
    ):
        raise HTTPException(
            status_code=404,
            detail=
                "Vídeo indisponível.",
        )

    path = (
        UPLOAD_DIR
        / video.file_name
    )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=
                "Arquivo não encontrado.",
        )

    return FileResponse(
        path,
        media_type=
            video.content_type,
        filename=
            video.original_file_name,
        # Sem isso, o Starlette usa "attachment" como default (por
        # causa de `filename=`), e o AVPlayer do app trata a resposta
        # como download em vez de mídia reproduzível inline — o
        # vídeo aparece com status "Aprovado" mas nunca carrega no
        # player.
        content_disposition_type=
            "inline",
    )


# MARK: Review


@router.get(
    "/{video_id}/review",
    response_class=HTMLResponse,
)
def review_video_page(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_review_token(
        video,
        token,
    )

    safe_title = html.escape(
        video.title
    )

    safe_description = html.escape(
        video.description or ""
    )

    safe_token = quote(
        token,
        safe="",
    )

    video_url = (
        f"/videos/{video.id}/review-file"
        f"?token={safe_token}"
    )

    approve_url = (
        f"/videos/{video.id}/review/approve"
        f"?token={safe_token}"
    )

    reject_url = (
        f"/videos/{video.id}/review/reject"
        f"?token={safe_token}"
    )

    return HTMLResponse(
        f"""
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Revisar vídeo
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 900px;
                    margin: 40px auto;
                    padding: 0 20px;
                "
            >
                <h1>
                    {safe_title}
                </h1>

                <p>
                    {safe_description}
                </p>

                <video
                    controls
                    preload="metadata"
                    playsinline
                    style="
                        width: 100%;
                        max-height: 520px;
                        background: #000;
                    "
                >
                    <source
                        src="{video_url}"
                        type="{video.content_type}"
                    >

                    Seu navegador não suporta
                    reprodução de vídeo.
                </video>

                <br>
                <br>

                <form
                    method="post"
                    action="{approve_url}"
                >
                    <button
                        type="submit"
                        style="
                            padding: 14px 22px;
                            background: green;
                            color: white;
                            border: 0;
                            border-radius: 8px;
                            font-size: 16px;
                            cursor: pointer;
                        "
                    >
                        Aprovar vídeo
                    </button>
                </form>

                <br>
                <br>

                <form
                    method="post"
                    action="{reject_url}"
                >
                    <textarea
                        name="reason"
                        placeholder="Motivo da rejeição"
                        required
                        rows="4"
                        style="
                            width: 100%;
                            max-width: 500px;
                            padding: 10px;
                        "
                    ></textarea>

                    <br>
                    <br>

                    <button
                        type="submit"
                        style="
                            padding: 14px 22px;
                            background: red;
                            color: white;
                            border: 0;
                            border-radius: 8px;
                            font-size: 16px;
                            cursor: pointer;
                        "
                    >
                        Rejeitar vídeo
                    </button>
                </form>
            </body>
        </html>
        """
    )

@router.get(
    "/{video_id}/review-file",
)
def review_video_file(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_review_token(
        video,
        token,
    )

    file_path = (
        UPLOAD_DIR
        / video.file_name
    )

    if not file_path.exists():
        print(
            """
            ❌ Arquivo do vídeo não existe

            Path:
            \(file_path)
            """
        )

        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado.",
        )

    print(
        f"""
🎬 Servindo vídeo para revisão

ID:
{video.id}

Arquivo:
{file_path}

Content-Type:
{video.content_type}

Tamanho:
{file_path.stat().st_size} bytes
""",
        flush=True,
    )

    return FileResponse(
        path=file_path,
        media_type=video.content_type,
        filename=video.original_file_name,
        content_disposition_type="inline",
    )

@router.post(
    "/{video_id}/review/approve",
    response_class=HTMLResponse,
)
def approve_video(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    print(
        f"""
✅ Entrou no endpoint de aprovação

Video ID:
{video_id}
""",
        flush=True,
    )

    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        print(
            f"""
❌ Vídeo não encontrado para aprovação

ID:
{video_id}
""",
            flush=True,
        )

        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_review_token(
        video,
        token,
    )

    if video.status == "approved":
        return HTMLResponse(
            """
            <!DOCTYPE html>

            <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">

                    <meta
                        name="viewport"
                        content="width=device-width, initial-scale=1"
                    >

                    <title>
                        Vídeo já aprovado
                    </title>
                </head>

                <body
                    style="
                        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                        max-width: 600px;
                        margin: 60px auto;
                        padding: 20px;
                        text-align: center;
                    "
                >
                    <h1>
                        ✅ Vídeo já aprovado
                    </h1>

                    <p>
                        Este vídeo já havia sido aprovado anteriormente.
                    </p>
                </body>
            </html>
            """
        )

    video.status = "approved"

    video.rejection_reason = None

    video.reviewed_at = (
        datetime.now(
            timezone.utc
        )
    )

    # Invalida o link de revisão: sem isso o mesmo token continuaria
    # válido por até 7 dias e poderia ser reutilizado para reverter
    # a decisão (ex.: aprovar e, em seguida, rejeitar com o mesmo link).
    video.review_token_expires_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(video)

    print(
        f"""
✅ Vídeo aprovado com sucesso

ID:
{video.id}

Status:
{video.status}
""",
        flush=True,
    )

    return HTMLResponse(
        """
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Vídeo aprovado
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 600px;
                    margin: 60px auto;
                    padding: 20px;
                    text-align: center;
                "
            >
                <div
                    style="
                        font-size: 64px;
                    "
                >
                    ✅
                </div>

                <h1>
                    Vídeo aprovado!
                </h1>

                <p>
                    O vídeo foi aprovado com sucesso
                    e agora poderá aparecer na Home
                    do TechStep.
                </p>
            </body>
        </html>
        """
    )

@router.post(
    "/{video_id}/review/reject",
    response_class=HTMLResponse,
)
def reject_video(
    video_id: UUID,
    token: str,
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    print(
        f"""
❌ Entrou no endpoint de rejeição

Video ID:
{video_id}
""",
        flush=True,
    )

    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_review_token(
        video,
        token,
    )

    normalized_reason = (
        reason.strip()
    )

    if not normalized_reason:
        raise HTTPException(
            status_code=422,
            detail=(
                "Informe o motivo "
                "da rejeição."
            ),
        )

    video.status = "rejected"

    video.rejection_reason = (
        normalized_reason
    )

    video.reviewed_at = (
        datetime.now(
            timezone.utc
        )
    )

    # Ver comentário equivalente em approve_video: invalida o link de
    # revisão para impedir reuso do token depois da decisão.
    video.review_token_expires_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(video)

    return HTMLResponse(
        """
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Vídeo rejeitado
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 600px;
                    margin: 60px auto;
                    padding: 20px;
                    text-align: center;
                "
            >
                <div
                    style="
                        font-size: 64px;
                    "
                >
                    ❌
                </div>

                <h1>
                    Vídeo rejeitado
                </h1>

                <p>
                    O vídeo foi rejeitado
                    e o motivo ficará disponível
                    para o usuário no aplicativo.
                </p>
            </body>
        </html>
        """
    )


# MARK: Thumbnail review


@router.get(
    "/{video_id}/thumbnail-review",
    response_class=HTMLResponse,
)
def review_thumbnail_page(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_thumbnail_review_token(
        video,
        token,
    )

    safe_title = html.escape(
        video.title
    )

    safe_token = quote(
        token,
        safe="",
    )

    image_url = (
        f"/videos/{video.id}/thumbnail-review-file"
        f"?token={safe_token}"
    )

    approve_url = (
        f"/videos/{video.id}/thumbnail-review/approve"
        f"?token={safe_token}"
    )

    reject_url = (
        f"/videos/{video.id}/thumbnail-review/reject"
        f"?token={safe_token}"
    )

    return HTMLResponse(
        f"""
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Revisar thumbnail
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 900px;
                    margin: 40px auto;
                    padding: 0 20px;
                "
            >
                <h1>
                    Thumbnail de: {safe_title}
                </h1>

                <img
                    src="{image_url}"
                    style="
                        width: 100%;
                        max-height: 520px;
                        object-fit: contain;
                        background: #000;
                    "
                >

                <br>
                <br>

                <form
                    method="post"
                    action="{approve_url}"
                >
                    <button
                        type="submit"
                        style="
                            padding: 14px 22px;
                            background: green;
                            color: white;
                            border: 0;
                            border-radius: 8px;
                            font-size: 16px;
                            cursor: pointer;
                        "
                    >
                        Aprovar thumbnail
                    </button>
                </form>

                <br>
                <br>

                <form
                    method="post"
                    action="{reject_url}"
                >
                    <textarea
                        name="reason"
                        placeholder="Motivo da rejeição"
                        required
                        rows="4"
                        style="
                            width: 100%;
                            max-width: 500px;
                            padding: 10px;
                        "
                    ></textarea>

                    <br>
                    <br>

                    <button
                        type="submit"
                        style="
                            padding: 14px 22px;
                            background: red;
                            color: white;
                            border: 0;
                            border-radius: 8px;
                            font-size: 16px;
                            cursor: pointer;
                        "
                    >
                        Rejeitar thumbnail
                    </button>
                </form>
            </body>
        </html>
        """
    )


@router.get(
    "/{video_id}/thumbnail-review-file",
)
def review_thumbnail_file(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_thumbnail_review_token(
        video,
        token,
    )

    if not video.pending_thumbnail_file_name:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma thumbnail pendente.",
        )

    file_path = (
        THUMBNAIL_UPLOAD_DIR
        / video.pending_thumbnail_file_name
    )

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado.",
        )

    media_type = (
        "image/png"
        if file_path.suffix == ".png"
        else "image/jpeg"
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
    )


@router.post(
    "/{video_id}/thumbnail-review/approve",
    response_class=HTMLResponse,
)
def approve_thumbnail(
    video_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_thumbnail_review_token(
        video,
        token,
    )

    if not video.pending_thumbnail_file_name:
        return HTMLResponse(
            """
            <!DOCTYPE html>

            <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">

                    <meta
                        name="viewport"
                        content="width=device-width, initial-scale=1"
                    >

                    <title>
                        Thumbnail já revisada
                    </title>
                </head>

                <body
                    style="
                        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                        max-width: 600px;
                        margin: 60px auto;
                        padding: 20px;
                        text-align: center;
                    "
                >
                    <h1>
                        ✅ Thumbnail já revisada
                    </h1>

                    <p>
                        Esta thumbnail já havia sido aprovada
                        ou rejeitada anteriormente.
                    </p>
                </body>
            </html>
            """
        )

    old_live_file_name = (
        video.thumbnail_file_name
    )

    video.thumbnail_file_name = (
        video.pending_thumbnail_file_name
    )

    video.thumbnail_source = "custom"
    video.pending_thumbnail_file_name = None
    video.thumbnail_rejection_reason = None

    # Ver comentário equivalente em approve_video: invalida o link de
    # revisão para impedir reuso do token depois da decisão.
    video.thumbnail_review_token_expires_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(video)

    _delete_thumbnail_file(
        old_live_file_name
    )

    logger.info(
        "thumbnail approved",
        extra={
            "event": "thumbnail_approved",
            "videoId": str(video_id),
        },
    )

    return HTMLResponse(
        """
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Thumbnail aprovada
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 600px;
                    margin: 60px auto;
                    padding: 20px;
                    text-align: center;
                "
            >
                <div
                    style="
                        font-size: 64px;
                    "
                >
                    ✅
                </div>

                <h1>
                    Thumbnail aprovada!
                </h1>

                <p>
                    A imagem enviada agora é a
                    thumbnail exibida para todos
                    os usuários do TechStep.
                </p>
            </body>
        </html>
        """
    )


@router.post(
    "/{video_id}/thumbnail-review/reject",
    response_class=HTMLResponse,
)
def reject_thumbnail(
    video_id: UUID,
    token: str,
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    video = (
        db.query(models.Video)
        .filter(
            models.Video.id
            == video_id
        )
        .first()
    )

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Vídeo não encontrado.",
        )

    validate_thumbnail_review_token(
        video,
        token,
    )

    normalized_reason = (
        reason.strip()
    )

    if not normalized_reason:
        raise HTTPException(
            status_code=422,
            detail=(
                "Informe o motivo "
                "da rejeição."
            ),
        )

    rejected_file_name = (
        video.pending_thumbnail_file_name
    )

    video.pending_thumbnail_file_name = None
    video.thumbnail_rejection_reason = normalized_reason

    # Ver comentário equivalente em reject_video: invalida o link de
    # revisão para impedir reuso do token depois da decisão.
    video.thumbnail_review_token_expires_at = (
        datetime.now(timezone.utc)
    )

    db.commit()
    db.refresh(video)

    _delete_thumbnail_file(
        rejected_file_name
    )

    return HTMLResponse(
        """
        <!DOCTYPE html>

        <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">

                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >

                <title>
                    Thumbnail rejeitada
                </title>
            </head>

            <body
                style="
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    max-width: 600px;
                    margin: 60px auto;
                    padding: 20px;
                    text-align: center;
                "
            >
                <div
                    style="
                        font-size: 64px;
                    "
                >
                    ❌
                </div>

                <h1>
                    Thumbnail rejeitada
                </h1>

                <p>
                    A imagem foi rejeitada e o motivo
                    ficará disponível para o usuário
                    no aplicativo. A thumbnail atual
                    não foi alterada.
                </p>
            </body>
        </html>
        """
    )