from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
)


class ReactionType(str, Enum):
    like = "like"
    dislike = "dislike"


class VideoReactionRequest(BaseModel):
    reaction: ReactionType


class VideoOut(BaseModel):
    id: UUID
    user_id: UUID

    title: str
    description: str | None

    status: str
    rejection_reason: str | None

    created_at: datetime
    reviewed_at: datetime | None

    stream_path: str | None = None

    # Só preenchido quando status == "pending": quando o botão de
    # reenviar a notificação de revisão volta a ficar disponível
    # (1x por dia por vídeo).
    next_resend_allowed_at: datetime | None = None

    # --- Thumbnail ---

    # Caminho relativo da thumbnail "ao vivo" (gerada automaticamente
    # ou última customizada aprovada) — None só quando nenhum frame
    # pôde ser gerado no upload.
    thumbnail_url: str | None = None

    # "auto" | "pending" | "approved" | "rejected". "pending" e
    # "rejected" descrevem o estado de uma edição enviada pelo
    # usuário — a imagem em thumbnail_url continua sendo a anterior
    # (auto ou último approved) enquanto isso.
    thumbnail_status: str = "auto"

    thumbnail_rejection_reason: str | None = None

    # Mesmo conceito de next_resend_allowed_at, para o reenvio do
    # e-mail de revisão da thumbnail pendente.
    thumbnail_next_resend_allowed_at: datetime | None = None

    # --- Reações e favoritos ---
    #
    # Só vêm preenchidos de verdade em endpoints com usuário
    # autenticado que calculam esses valores explicitamente (detalhe
    # do vídeo, reagir/favoritar, lista de favoritos) — nos demais
    # (upload, meus vídeos, lista pública, revisão) ficam nos
    # defaults abaixo, que não são exibidos pelo app nesses contextos.

    likes_count: int = 0
    dislikes_count: int = 0

    # "like" | "dislike" | None — reação do usuário autenticado da
    # requisição atual.
    my_reaction: str | None = None

    is_favorited: bool = False

    model_config = ConfigDict(
        from_attributes=True
    )


class ResendReviewResponse(BaseModel):
    video: VideoOut
    next_resend_allowed_at: datetime


class ResendThumbnailReviewResponse(BaseModel):
    video: VideoOut
    next_resend_allowed_at: datetime


class VideoPageResponse(BaseModel):
    items: list[VideoOut]

    page: int
    page_size: int

    total: int
    total_pages: int

    has_next: bool