from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class RateLimitBucket(Base):
    """Contador de janela fixa por chave, usado para rate limiting.

    Fica em Postgres (em vez de Redis/memória local) para que o limite
    seja compartilhado entre todas as instâncias da API. `key` já
    identifica o escopo + o cliente (ex.: "login:ip:1.2.3.4"), então
    não precisamos de colunas adicionais para diferenciar endpoints.
    """

    __tablename__ = "rate_limit_buckets"

    key = Column(String(255), primary_key=True)

    window_start = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
