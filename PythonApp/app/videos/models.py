import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    title = Column(
        String(150),
        nullable=False,
    )

    description = Column(
        Text,
        nullable=True,
    )

    file_name = Column(
        String(255),
        nullable=False,
    )

    original_file_name = Column(
        String(255),
        nullable=False,
    )

    content_type = Column(
        String(100),
        nullable=False,
    )

    size_bytes = Column(
        BigInteger,
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )

    rejection_reason = Column(
        Text,
        nullable=True,
    )

    review_token_hash = Column(
        String(64),
        nullable=False,
    )

    review_token_expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Quando o e-mail de "vídeo aguardando revisão" foi enviado pela
    # última vez (no upload, ou num reenvio manual) — usado para
    # limitar o botão de reenvio a 1x por dia por vídeo.
    review_notification_sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- Thumbnail ---
    #
    # `thumbnail_file_name` é sempre a imagem "ao vivo" (visível para
    # todo mundo): o frame gerado automaticamente no app a partir do
    # 1º segundo do vídeo, ou a última imagem customizada já aprovada.
    # Uma edição de thumbnail enviada pelo usuário nunca sobrescreve
    # esse arquivo diretamente — ela fica em `pending_thumbnail_*` até
    # ser aprovada por e-mail (mesmo mecanismo de token do vídeo),
    # exatamente para que trocar a thumbnail não publique uma imagem
    # não moderada instantaneamente.
    thumbnail_file_name = Column(
        String(255),
        nullable=True,
    )

    # "auto" (gerado no app, sem moderação) ou "custom" (imagem do
    # usuário já aprovada) — describe o arquivo atualmente em
    # `thumbnail_file_name`.
    thumbnail_source = Column(
        String(20),
        nullable=False,
        default="auto",
        server_default="auto",
    )

    pending_thumbnail_file_name = Column(
        String(255),
        nullable=True,
    )

    thumbnail_review_token_hash = Column(
        String(64),
        nullable=True,
    )

    thumbnail_review_token_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Mesmo propósito de review_notification_sent_at, mas para o
    # e-mail de revisão da thumbnail customizada pendente.
    thumbnail_review_notification_sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Motivo da última rejeição de thumbnail — fica disponível para o
    # usuário no app mesmo depois que a thumbnail "ao vivo" volta a
    # ser a anterior (auto ou último approved).
    thumbnail_rejection_reason = Column(
        Text,
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="videos",
    )


class VideoReaction(Base):
    __tablename__ = "video_reactions"

    # Um usuário só pode ter 1 reação por vídeo (like OU dislike) —
    # reagir de novo troca a reação existente em vez de acumular
    # linhas, garantido pela unique constraint abaixo.
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "user_id",
            name="uq_video_reactions_video_user",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    video_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "videos.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # "like" | "dislike"
    reaction = Column(
        String(10),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class VideoFavorite(Base):
    __tablename__ = "video_favorites"

    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "user_id",
            name="uq_video_favorites_video_user",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    video_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "videos.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )