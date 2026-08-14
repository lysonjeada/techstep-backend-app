import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
import app.auth.models
import app.tutors.models
import app.videos.models

# Caminho absoluto da pasta PythonApp.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Permite importar módulos começando por "app".
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Carrega PythonApp/.env antes de importar database.py.
load_dotenv(PROJECT_ROOT / ".env")

from alembic import context

# Usa exatamente o mesmo Base e engine da aplicação.
from app.database import Base, engine

# Esses imports registram todas as tabelas no Base.metadata.
from app import models as app_models
from app.interview_simulation import models as interview_simulation_models


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    database_url = engine.url.render_as_string(
        hide_password=False
    )

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()