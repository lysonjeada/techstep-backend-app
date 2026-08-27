from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

import uuid

from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

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

    family_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        default=uuid.uuid4,
    )

    token_hash = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    revoked_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user = relationship(
        "User",
        back_populates="refresh_tokens",
    )


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
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

    code_hash = Column(
        String(64),
        nullable=False,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    last_sent_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    is_used = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    user = relationship(
        "User",
        back_populates="verification_codes",
    )


class PasswordResetCode(Base):
    """Código de 6 dígitos enviado por e-mail para o fluxo de "esqueci
    minha senha". Tabela própria (em vez de reaproveitar
    EmailVerificationCode) porque as duas coisas têm propósitos e
    ciclos de vida diferentes — misturar as duas na mesma tabela sem
    uma coluna de propósito arriscaria um código de cadastro validar
    um reset de senha por engano."""

    __tablename__ = "password_reset_codes"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
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

    code_hash = Column(
        String(64),
        nullable=False,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    last_sent_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    is_used = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    user = relationship(
        "User",
        back_populates="password_reset_codes",
    )


class PasswordResetToken(Base):
    """Token opaco de uso único emitido depois que o código acima é
    validado. Só ele autoriza a troca de senha em si — o e-mail não é
    exigido de novo no passo final porque este token já identifica o
    usuário (ver app.auth.password_reset_service)."""

    __tablename__ = "password_reset_tokens"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
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

    token_hash = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    used_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user = relationship(
        "User",
        back_populates="password_reset_tokens",
    )