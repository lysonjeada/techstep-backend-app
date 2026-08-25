"""add video thumbnail

Revision ID: 48b43604b69f
Revises: 99065c18622b
Create Date: 2026-08-25 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '48b43604b69f'
down_revision: Union[str, Sequence[str], None] = '99065c18622b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_file_name',
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_source',
            sa.String(length=20),
            nullable=False,
            server_default='auto',
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'pending_thumbnail_file_name',
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_review_token_hash',
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_review_token_expires_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_review_notification_sent_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        'videos',
        sa.Column(
            'thumbnail_rejection_reason',
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('videos', 'thumbnail_rejection_reason')
    op.drop_column('videos', 'thumbnail_review_notification_sent_at')
    op.drop_column('videos', 'thumbnail_review_token_expires_at')
    op.drop_column('videos', 'thumbnail_review_token_hash')
    op.drop_column('videos', 'pending_thumbnail_file_name')
    op.drop_column('videos', 'thumbnail_source')
    op.drop_column('videos', 'thumbnail_file_name')
