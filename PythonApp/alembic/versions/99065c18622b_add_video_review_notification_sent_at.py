"""add video review notification sent at

Revision ID: 99065c18622b
Revises: 9fb2fa056c12
Create Date: 2026-08-24 16:24:27.557137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '99065c18622b'
down_revision: Union[str, Sequence[str], None] = '9fb2fa056c12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'videos',
        sa.Column(
            'review_notification_sent_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('videos', 'review_notification_sent_at')
