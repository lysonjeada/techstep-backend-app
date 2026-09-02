"""add user_id to interview_question_sets

Revision ID: db0f2d88d4fd
Revises: c0c29cd62b92
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'db0f2d88d4fd'
down_revision: Union[str, Sequence[str], None] = 'c0c29cd62b92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable: o endpoint de salvar nunca exigiu autenticação até
    # agora, então linhas pré-existentes (se houver) não têm dono
    # conhecido e ficam com user_id NULL — simplesmente não aparecem
    # na listagem "minhas perguntas salvas" de ninguém.
    op.add_column(
        'interview_question_sets',
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=True,
        ),
    )

    op.create_index(
        'ix_interview_question_sets_user_id',
        'interview_question_sets',
        ['user_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_interview_question_sets_user_id',
        table_name='interview_question_sets',
    )
    op.drop_column('interview_question_sets', 'user_id')
