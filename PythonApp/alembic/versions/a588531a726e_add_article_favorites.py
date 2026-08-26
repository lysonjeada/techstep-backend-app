"""add article favorites

Revision ID: a588531a726e
Revises: df70a7ff4640
Create Date: 2026-08-26 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a588531a726e'
down_revision: Union[str, Sequence[str], None] = 'df70a7ff4640'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'article_favorites',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column('article_id', sa.Integer(), nullable=False),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            'article_id', 'user_id',
            name='uq_article_favorites_article_user',
        ),
    )

    op.create_index(
        'ix_article_favorites_article_id',
        'article_favorites',
        ['article_id'],
    )

    op.create_index(
        'ix_article_favorites_user_id',
        'article_favorites',
        ['user_id'],
    )

    # Ver comentário equivalente na migration de video_reactions —
    # RLS habilitado desde a criação, o linter da Supabase acusa
    # ERROR em qualquer tabela public sem isso.
    op.execute(
        'ALTER TABLE public.article_favorites ENABLE ROW LEVEL SECURITY;'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('article_favorites')
