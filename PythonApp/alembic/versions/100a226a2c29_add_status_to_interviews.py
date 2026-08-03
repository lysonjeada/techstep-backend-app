"""add status to interviews

Revision ID: 100a226a2c29
Revises: d9eb98c55423
Create Date: 2026-07-31 12:58:05.604837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '100a226a2c29'
down_revision: Union[str, Sequence[str], None] = 'd9eb98c55423'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
