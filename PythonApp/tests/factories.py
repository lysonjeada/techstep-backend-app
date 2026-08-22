import uuid
from datetime import datetime, timedelta, timezone

from app import models
from app.auth.security import hash_password
from app.videos import models as video_models


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def create_user(
    db,
    *,
    email=None,
    username=None,
    password="Senha123!",
    is_active=True,
    is_email_verified=True,
):
    suffix = unique_suffix()

    user = models.User(
        email=email or f"user-{suffix}@example.com",
        username=username or f"user_{suffix}",
        hashed_password=hash_password(password),
        is_active=is_active,
        is_email_verified=is_email_verified,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def create_interview(db, user, **overrides):
    defaults = dict(
        user_id=user.id,
        company_name="Empresa Teste",
        job_title="Engenheiro de Software",
        job_seniority="Pleno",
        status="applied",
        skills=[],
    )

    defaults.update(overrides)

    interview = models.Interview(**defaults)

    db.add(interview)
    db.commit()
    db.refresh(interview)

    return interview


def create_video(db, user, **overrides):
    suffix = unique_suffix()

    defaults = dict(
        user_id=user.id,
        title="Vídeo de apresentação",
        description=None,
        file_name=f"{suffix}.mp4",
        original_file_name="video.mp4",
        content_type="video/mp4",
        size_bytes=1024,
        status="pending",
        review_token_hash="0" * 64,
        review_token_expires_at=(
            datetime.now(timezone.utc) + timedelta(days=1)
        ),
    )

    defaults.update(overrides)

    video = video_models.Video(**defaults)

    db.add(video)
    db.commit()
    db.refresh(video)

    return video


def create_refresh_token_row(db, user, **overrides):
    from app.auth.models import RefreshToken

    defaults = dict(
        user_id=user.id,
        family_id=uuid.uuid4(),
        token_hash="0" * 64,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=30)
        ),
    )

    defaults.update(overrides)

    token = RefreshToken(**defaults)

    db.add(token)
    db.commit()
    db.refresh(token)

    return token
