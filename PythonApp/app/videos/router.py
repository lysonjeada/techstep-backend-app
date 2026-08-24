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
    VIDEO_UPLOAD_MAX,
    VIDEO_UPLOAD_WINDOW_SECONDS,
    user_rate_limiter,
)

from . import (
    models,
    schemas,
)

from .email_service import (
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


ALLOWED_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-m4v",
    "video/webm",
}


def hash_review_token(
    token: str,
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def serialize_video(
    video: models.Video,
) -> schemas.VideoOut:
    stream_path = None

    if video.status == "approved":
        stream_path = (
            f"/videos/{video.id}/file"
        )

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

    suffix = Path(
        file.filename or ""
    ).suffix.lower()

    if not suffix:
        suffix = ".mp4"

    saved_file_name = (
        f"{video_id}{suffix}"
    )

    file_path = (
        UPLOAD_DIR
        / saved_file_name
    )

    size = 0

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

    except Exception:
        if file_path.exists():
            file_path.unlink()

        raise

    finally:
        await file.close()

    review_token = (
        secrets.token_urlsafe(32)
    )

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
    )

    try:
        db.add(video)
        db.commit()
        db.refresh(video)

    except Exception:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        raise

    review_url = (
        f"{PUBLIC_API_URL}"
        f"/videos/{video.id}"
        f"/review"
        f"?token={quote(review_token)}"
    )

    background_tasks.add_task(
        send_video_review_email,
        title=video.title,
        uploader_email=
            current_user.email,
        review_url=review_url,
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