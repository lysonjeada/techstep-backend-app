"""add password reset codes and tokens

Revision ID: c0c29cd62b92
Revises: a588531a726e
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c0c29cd62b92'
down_revision: Union[str, Sequence[str], None] = 'a588531a726e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'password_reset_codes',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'last_sent_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'attempts',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'is_used',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )

    op.create_index(
        'ix_password_reset_codes_user_id',
        'password_reset_codes',
        ['user_id'],
    )

    op.create_table(
        'password_reset_tokens',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'token_hash',
            sa.String(length=64),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'used_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        'ix_password_reset_tokens_user_id',
        'password_reset_tokens',
        ['user_id'],
    )

    op.create_index(
        'ix_password_reset_tokens_token_hash',
        'password_reset_tokens',
        ['token_hash'],
        unique=True,
    )

    # Ver comentário equivalente na migration de article_favorites —
    # RLS habilitado desde a criação, o linter da Supabase acusa
    # ERROR em qualquer tabela public sem isso. O backend conecta como
    # postgres (superuser, bypassa RLS), então isso não muda nenhum
    # comportamento da aplicação.
    op.execute(
        'ALTER TABLE public.password_reset_codes '
        'ENABLE ROW LEVEL SECURITY;'
    )
    op.execute(
        'ALTER TABLE public.password_reset_tokens '
        'ENABLE ROW LEVEL SECURITY;'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('password_reset_tokens')
    op.drop_table('password_reset_codes')
