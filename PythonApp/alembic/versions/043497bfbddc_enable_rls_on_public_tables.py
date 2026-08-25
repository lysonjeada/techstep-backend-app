"""enable rls on public tables

O banco roda no Supabase, que expõe automaticamente todas as
tabelas do schema `public` via uma API REST pública (PostgREST) para
os papéis `anon`/`authenticated`, a menos que Row Level Security
esteja habilitado. Nenhuma tabela deste projeto tinha RLS ativado —
o linter de segurança do Supabase acusou isso como ERROR em todas
as 12 tabelas (incluindo `users`, `refresh_tokens` e
`email_verification_codes`).

Este backend nunca usa a API PostgREST do Supabase — ele acessa o
Postgres direto via SQLAlchemy, autenticado como o papel `postgres`
(superusuário, `rolbypassrls = true`), que ignora RLS
completamente. Então habilitar RLS aqui, sem nenhuma policy, tem
efeito zero no backend e fecha por completo o acesso público via
PostgREST para `anon`/`authenticated` (nega tudo por padrão quando
RLS está ligado sem policies).

Revision ID: 043497bfbddc
Revises: 48b43604b69f
Create Date: 2026-08-25 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '043497bfbddc'
down_revision: Union[str, Sequence[str], None] = '48b43604b69f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    'alembic_version',
    'users',
    'email_verification_codes',
    'interviews',
    'refresh_tokens',
    'interview_question_sets',
    'saved_interview_questions',
    'tutor_profiles',
    'videos',
    'rate_limit_buckets',
    'ai_credit_balances',
    'ai_credit_purchases',
]


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.execute(
            f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;'
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.execute(
            f'ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;'
        )
