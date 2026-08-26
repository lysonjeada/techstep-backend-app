"""add video reactions and favorites

Revision ID: df70a7ff4640
Revises: 043497bfbddc
Create Date: 2026-08-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'df70a7ff4640'
down_revision: Union[str, Sequence[str], None] = '043497bfbddc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'video_reactions',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            'video_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('videos.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('reaction', sa.String(length=10), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            'video_id', 'user_id',
            name='uq_video_reactions_video_user',
        ),
    )

    op.create_index(
        'ix_video_reactions_video_id',
        'video_reactions',
        ['video_id'],
    )

    op.create_index(
        'ix_video_reactions_user_id',
        'video_reactions',
        ['user_id'],
    )

    op.create_table(
        'video_favorites',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            'video_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('videos.id', ondelete='CASCADE'),
            nullable=False,
        ),
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
            'video_id', 'user_id',
            name='uq_video_favorites_video_user',
        ),
    )

    op.create_index(
        'ix_video_favorites_video_id',
        'video_favorites',
        ['video_id'],
    )

    op.create_index(
        'ix_video_favorites_user_id',
        'video_favorites',
        ['user_id'],
    )

    # O linter de segurança do Supabase acusa ERROR em qualquer tabela
    # public sem RLS (fica exposta via PostgREST) — já vimos isso
    # acontecer com as tabelas antigas. Habilitamos aqui desde a
    # criação para as novas não caírem no mesmo problema. O backend
    # conecta como `postgres` (bypassrls=true), então isso não afeta
    # em nada as queries da aplicação.
    op.execute(
        'ALTER TABLE public.video_reactions ENABLE ROW LEVEL SECURITY;'
    )

    op.execute(
        'ALTER TABLE public.video_favorites ENABLE ROW LEVEL SECURITY;'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('video_favorites')
    op.drop_table('video_reactions')
