"""add user id to interviews

Revision ID: c5d1dc5939b9
Revises: 594713487f98
Create Date: 2026-08-11 19:09:10.296953
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5d1dc5939b9"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "594713487f98"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    # As entrevistas antigas não possuem usuário.
    # Portanto, removemos esses registros antes
    # de tornar user_id obrigatório.
    op.execute(
        "DELETE FROM interviews"
    )

    op.add_column(
        "interviews",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_interviews_user_id",
        "interviews",
        ["user_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_interviews_user_id",
        "interviews",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_interviews_user_id",
        "interviews",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_interviews_user_id",
        table_name="interviews",
    )

    op.drop_column(
        "interviews",
        "user_id",
    )