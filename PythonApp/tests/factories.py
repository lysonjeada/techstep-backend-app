import uuid
from datetime import datetime, timedelta, timezone

from app import models
from app.auth.security import hash_password
from app.videos import models as video_models


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


# --- payloads de upload com magic bytes válidos ---
#
# app.uploads.validation valida o conteúdo real do arquivo (magic
# bytes), não só o Content-Type declarado. Testes de upload que
# esperam sucesso (2xx) precisam de bytes que passem nessa validação;
# testes que querem provar a rejeição de conteúdo inválido usam
# FAKE_TEXT_BYTES ou qualquer coisa que não bata com as assinaturas
# abaixo.

# Box "ftyp" no offset 4 = ISO-BMFF (MP4/MOV/M4V vídeo, MP4/M4A áudio).
FAKE_MP4_BYTES = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    b"fake mp4 payload for tests"
)
FAKE_M4A_BYTES = FAKE_MP4_BYTES

# Assinatura EBML do WebM/Matroska.
FAKE_WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"fake webm payload for tests"

# Assinatura "%PDF-" exigida no início do arquivo.
FAKE_PDF_BYTES = b"%PDF-1.4\n" + b"fake pdf payload for tests"

# Não bate com nenhuma assinatura acima — usado para testar rejeicao.
FAKE_TEXT_BYTES = b"isso definitivamente nao e um arquivo de midia"


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


def create_ai_credit_balance(db, user, balance=0):
    from app.credits import service as credits_service

    credits_service.ensure_balance_row(db, user.id)

    if balance:
        credits_service.credit(db, user.id, balance)

    return credits_service.get_balance(db, user.id)


def create_ai_credit_purchase(db, user, **overrides):
    from app.credits.models import AICreditPurchase

    suffix = unique_suffix()

    defaults = dict(
        user_id=user.id,
        apple_transaction_id=f"apple-txn-{suffix}",
        apple_original_transaction_id=f"apple-txn-{suffix}",
        product_id="lys.com.career-app.credits.10",
        credits_granted=10,
        environment="Sandbox",
    )

    defaults.update(overrides)

    purchase = AICreditPurchase(**defaults)

    db.add(purchase)
    db.commit()
    db.refresh(purchase)

    return purchase


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
