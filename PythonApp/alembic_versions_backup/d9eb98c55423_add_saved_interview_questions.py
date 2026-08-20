"""add saved interview questions

Revision ID: d9eb98c55423
Revises: 2327a284f19f
Create Date: 2026-07-23 09:55:21.738752

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9eb98c55423'
down_revision: Union[str, Sequence[str], None] = '2327a284f19f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
