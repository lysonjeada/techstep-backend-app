"""add saved interview questions

Revision ID: 2327a284f19f
Revises: edd07dd0cde2
Create Date: 2026-07-23 09:48:08.729503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2327a284f19f'
down_revision: Union[str, Sequence[str], None] = 'edd07dd0cde2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
