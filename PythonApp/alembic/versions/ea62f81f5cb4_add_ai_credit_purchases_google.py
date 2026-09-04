"""add ai credit purchases google

Revision ID: ea62f81f5cb4
Revises: db0f2d88d4fd
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea62f81f5cb4'
down_revision: Union[str, Sequence[str], None] = 'db0f2d88d4fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_credit_purchases_google',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('google_order_id', sa.String(length=255), nullable=False),
    sa.Column('product_id', sa.String(length=255), nullable=False),
    sa.Column('credits_granted', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('google_order_id')
    )
    op.create_index(op.f('ix_ai_credit_purchases_google_user_id'), 'ai_credit_purchases_google', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ai_credit_purchases_google_user_id'), table_name='ai_credit_purchases_google')
    op.drop_table('ai_credit_purchases_google')
