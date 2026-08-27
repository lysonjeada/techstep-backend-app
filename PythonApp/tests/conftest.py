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

os.environ.setdefault("PASSWORD_RESET_CODE_EXPIRATION_MINUTES", "10")
os.environ.setdefault("PASSWORD_RESET_CODE_RESEND_SECONDS", "60")
os.environ.setdefault("PASSWORD_RESET_CODE_MAX_ATTEMPTS", "5")
os.environ.setdefault("PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES", "10")

os.environ.setdefault("GITHUB_TOKEN", "test-github-token")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

_TEST_UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="techstep-test-uploads-"))
os.environ.setdefault("VIDEO_UPLOAD_DIR", str(_TEST_UPLOAD_DIR))
os.environ.setdefault("PUBLIC_API_URL", "http://testserver")

import socket

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.auth.dependencies import get_current_user
from app.auth.token_service import create_access_token
from app.database import Base, engine, get_db

from tests import factories


class _BlockedNetworkCall(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_real_network_calls(monkeypatch):
    """Rede de proteção: nenhum teste pode escapar para a internet real.

    Isso cobre chamadas OpenAI e SMTP não mockadas (e qualquer outro
    socket TCP real), mesmo que um teste individual esqueça de mockar
    o client. Conexões ao Postgres de teste continuam funcionando
    porque psycopg2 fala com o socket via extensão C, fora do alcance
    do módulo `socket` do Python.
    """

    def _blocked_connect(self, address, *args, **kwargs):
        raise _BlockedNetworkCall(
            "Chamada de rede real bloqueada durante os testes "
            f"(destino: {address!r}). Mocke o client/serviço externo."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect)


@pytest.fixture(autouse=True)
def _mock_verification_email(monkeypatch):
    """SMTP nunca é configurado em ambiente de teste (de propósito).

    Sem este mock, qualquer endpoint que dispare
    `send_verification_email` em background (register/resend) estouraria
    RuntimeError por falta de config SMTP. Testes que querem inspecionar
    a chamada podem sobrescrever `app.auth.router.send_verification_email`
    novamente com seu próprio monkeypatch.
    """

    import app.auth.router as auth_router_module

    sent_emails = []

    def _fake_send(recipient_email, recipient_name, code):
        sent_emails.append(
            {
                "email": recipient_email,
                "name": recipient_name,
                "code": code,
            }
        )

    monkeypatch.setattr(
        auth_router_module, "send_verification_email", _fake_send
    )

    return sent_emails


@pytest.fixture(autouse=True)
def _mock_password_reset_email(monkeypatch):
    """Mesma ideia de _mock_verification_email, para o e-mail de
    código de redefinição de senha disparado em background por
    POST /users/forgot-password."""

    import app.auth.router as auth_router_module

    sent_emails = []

    def _fake_send(recipient_email, recipient_name, code):
        sent_emails.append(
            {
                "email": recipient_email,
                "name": recipient_name,
                "code": code,
            }
        )

    monkeypatch.setattr(
        auth_router_module, "send_password_reset_email", _fake_send
    )

    return sent_emails


@pytest.fixture(autouse=True)
def _mock_video_review_email(monkeypatch):
    """Mesma ideia acima, para o e-mail de "vídeo aguardando revisão"
    disparado em background pelo upload de vídeo. Sem isso, qualquer
    teste que faça upload real (via POST /videos/) estouraria a rede
    de proteção contra chamadas SMTP reais.
    """

    import app.videos.router as videos_router_module

    sent_review_emails = []

    def _fake_send(*, title, uploader_email, review_url):
        sent_review_emails.append(
            {
                "title": title,
                "uploader_email": uploader_email,
                "review_url": review_url,
            }
        )

    monkeypatch.setattr(
        videos_router_module,
        "send_video_review_email",
        _fake_send,
    )

    return sent_review_emails


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
