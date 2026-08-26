import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class ArticleFavorite(Base):
    __tablename__ = "article_favorites"

    # Um usuário só pode favoritar o mesmo artigo uma vez.
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "user_id",
            name="uq_article_favorites_article_user",
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Id numérico do artigo no dev.to — não é FK (recurso externo,
    # não temos uma tabela local de artigos).
    article_id = Column(
        Integer,
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
