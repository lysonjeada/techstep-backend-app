import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# As variáveis de ambiente precisam existir ANTES de qualquer import de
# app.*, porque vários módulos (openai_client, llm_generation/router,
# interview_simulation/router, worker/tasks, database, videos/router)
# leem env vars e criam clients/engines/diretórios no momento do import.

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/techstep_test",
)

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-jwt-secret-key-with-enough-entropy-for-hs256",
)
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "30")

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("OPENAI_MODEL", "gpt-4")
os.environ.setdefault("OPENAI_INTERVIEW_MODEL", "gpt-4")

os.environ.setdefault("EMAIL_VERIFICATION_PEPPER", "test-verification-pepper")
os.environ.setdefault("EMAIL_VERIFICATION_EXPIRATION_MINUTES", "10")
os.environ.setdefault("EMAIL_VERIFICATION_RESEND_SECONDS", "60")
os.environ.setdefault("EMAIL_VERIFICATION_MAX_ATTEMPTS", "5")

os.environ.setdefault("GITHUB_TOKEN", "test-github-token")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

_TEST_UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="techstep-test-uploads-"))
os.environ.setdefault("VIDEO_UPLOAD_DIR", str(_TEST_UPLOAD_DIR))
os.environ.setdefault("PUBLIC_API_URL", "http://testserver")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.auth.dependencies import get_current_user
from app.auth.token_service import create_access_token
from app.database import Base, engine, get_db

from tests import factories


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield

    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()

    TestingSessionLocal = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )

    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def app_instance(db_session):
    main_module.app.dependency_overrides[get_db] = lambda: db_session

    yield main_module.app

    main_module.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
async def client(app_instance):
    transport = ASGITransport(app=app_instance)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.fixture()
def user(db_session):
    return factories.create_user(db_session)


@pytest.fixture()
def second_user(db_session):
    return factories.create_user(db_session)


def auth_headers_for(user_row):
    token = create_access_token(user_row.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def authenticated_client(client, user):
    client.headers.update(auth_headers_for(user))
    yield client


@pytest.fixture()
async def authenticated_client_b(app_instance, second_user):
    transport = ASGITransport(app=app_instance)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=auth_headers_for(second_user),
    ) as async_client:
        yield async_client
