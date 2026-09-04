import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class AICreditBalance(Base):
    """Saldo de créditos de IA de um usuário — sempre a fonte da verdade,
    nunca o device. Uma linha por usuário, criada sob demanda (upsert
    idempotente) na primeira operação de saldo, não no cadastro."""

    __tablename__ = "ai_credit_balances"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    balance = Column(
        Integer,
        nullable=False,
        server_default="0",
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "balance >= 0",
            name="ck_ai_credit_balances_non_negative",
        ),
    )


class AICreditPurchase(Base):
    """Ledger auditável de compras Apple. UNIQUE em apple_transaction_id
    é o que garante idempotência: a mesma transação nunca credita duas
    vezes, mesmo sob requisições concorrentes (o INSERT falha com
    IntegrityError, nunca um SELECT-then-INSERT)."""

    __tablename__ = "ai_credit_purchases"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    apple_transaction_id = Column(
        String(255),
        nullable=False,
        unique=True,
    )

    apple_original_transaction_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    product_id = Column(
        String(255),
        nullable=False,
    )

    credits_granted = Column(
        Integer,
        nullable=False,
    )

    environment = Column(
        String(20),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AICreditPurchaseGoogle(Base):
    """Ledger auditável de compras Google Play — mesmo padrão de
    AICreditPurchase (Apple): UNIQUE em google_order_id é o que garante
    idempotência (o INSERT falha com IntegrityError num reenvio, nunca
    um SELECT-then-INSERT)."""

    __tablename__ = "ai_credit_purchases_google"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    google_order_id = Column(
        String(255),
        nullable=False,
        unique=True,
    )

    product_id = Column(
        String(255),
        nullable=False,
    )

    credits_granted = Column(
        Integer,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
