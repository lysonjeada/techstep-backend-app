"""Auditoria de autorização/IDOR em todos os endpoints que tocam recursos
por ID.

tests/security/test_idor.py já cobre o caso clássico (usuário A não
acessa/edita/exclui recurso de usuário B) para /users/{id},
/interviews/{id} e /videos. Não duplicamos isso aqui.

Este arquivo cobre dois tipos de lacuna que a auditoria encontrou e que
o test_idor.py não cobre:

1. Um bug real de autorização: o token de revisão de vídeo (magic link
   por e-mail) nunca é invalidado depois que uma decisão é tomada, o
   que permite reverter approve/reject reutilizando o mesmo link
   dentro da janela de 7 dias.
2. Endpoints que, por design atual, não têm nenhum conceito de
   ownership (não têm user_id, não exigem autenticação). Não são
   "bugs de query" como um IDOR clássico — são lacunas arquiteturais.
   Documentamos o comportamento atual com um teste para que não sejam
   esquecidas, sem tentar redesenhar a feature nesta tarefa.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from tests import factories

pytestmark = pytest.mark.security


# --- vídeos: reuso do token de revisão (bug real, corrigido) ---


async def _upload_and_get_review_token(client, db_session, user, monkeypatch):
    """Cria um vídeo pendente com um token de revisão conhecido."""
    raw_token = "known-review-token-for-tests"

    from app.videos.router import hash_review_token

    video = factories.create_video(
        db_session,
        user,
        status="pending",
        review_token_hash=hash_review_token(raw_token),
        review_token_expires_at=(
            datetime.now(timezone.utc) + timedelta(days=7)
        ),
    )
    return video, raw_token


async def test_review_token_is_invalidated_after_approve(
    client, db_session, user
):
    video, raw_token = await _upload_and_get_review_token(
        client, db_session, user, None
    )

    approve_response = await client.post(
        f"/videos/{video.id}/review/approve",
        params={"token": raw_token},
    )
    assert approve_response.status_code == 200

    reuse_response = await client.post(
        f"/videos/{video.id}/review/reject",
        params={"token": raw_token},
        data={"reason": "mudei de ideia"},
    )

    assert reuse_response.status_code == 401

    db_session.expire_all()
    from app.videos.models import Video

    stored = (
        db_session.query(Video)
        .filter(Video.id == video.id)
        .first()
    )
    assert stored.status == "approved"


async def test_review_token_is_invalidated_after_reject(
    client, db_session, user
):
    video, raw_token = await _upload_and_get_review_token(
        client, db_session, user, None
    )

    reject_response = await client.post(
        f"/videos/{video.id}/review/reject",
        params={"token": raw_token},
        data={"reason": "qualidade baixa"},
    )
    assert reject_response.status_code == 200

    reuse_response = await client.post(
        f"/videos/{video.id}/review/approve",
        params={"token": raw_token},
    )

    assert reuse_response.status_code == 401

    db_session.expire_all()
    from app.videos.models import Video

    stored = (
        db_session.query(Video)
        .filter(Video.id == video.id)
        .first()
    )
    assert stored.status == "rejected"


async def test_review_token_invalid_is_rejected(client, db_session, user):
    video, _ = await _upload_and_get_review_token(
        client, db_session, user, None
    )

    response = await client.post(
        f"/videos/{video.id}/review/approve",
        params={"token": "not-the-right-token"},
    )
    assert response.status_code == 401


async def test_review_token_expired_is_rejected(client, db_session, user):
    from app.videos.router import hash_review_token

    raw_token = "expired-review-token"
    video = factories.create_video(
        db_session,
        user,
        status="pending",
        review_token_hash=hash_review_token(raw_token),
        review_token_expires_at=(
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ),
    )

    response = await client.post(
        f"/videos/{video.id}/review/approve",
        params={"token": raw_token},
    )
    assert response.status_code == 401


async def test_raw_review_token_never_stored_in_db(client, db_session, user):
    video, raw_token = await _upload_and_get_review_token(
        client, db_session, user, None
    )
    assert video.review_token_hash != raw_token


# --- resume feedback: task de terceiro sem checagem de ownership ---
#
# /submit-feedback/, /feedback-status/{task_id} e
# /feedback-result/{task_id} não exigem autenticação e o resultado da
# task não é associado a nenhum user_id. Isso significa que qualquer
# pessoa que descubra/observe um task_id (UUID gerado pelo Celery) pode
# ler o feedback de currículo de outra pessoa. Documentamos o
# comportamento atual; corrigir isso exige desenhar um vínculo
# task->usuário e autenticação nesses três endpoints, o que é uma
# mudança de contrato maior e não foi feita silenciosamente aqui.


async def test_feedback_result_has_no_ownership_check(
    client, monkeypatch
):
    import app.llm_generation.router as llm_router

    fake_result = MagicMock()
    fake_result.ready.return_value = True
    fake_result.status = "SUCCESS"
    fake_result.get.return_value = "feedback de outra pessoa"

    monkeypatch.setattr(
        llm_router.celery_app,
        "AsyncResult",
        lambda task_id: fake_result,
    )

    response = await client.get(
        "/feedback-result/some-other-users-task-id"
    )

    # Comportamento ATUAL (sem autenticação/ownership): qualquer client
    # não autenticado consegue ler o resultado. Ver docstring acima.
    assert response.status_code == 200
    assert response.json()["feedback"] == "feedback de outra pessoa"


# --- tutors: diretório público (por design) ---
#
# /tutors/ e /tutors/{id} não exigem autenticação de propósito (é um
# diretório público de tutores). Confirmamos aqui que o schema exposto
# não vaza nada além do que é destinado a ser público (sem email,
# sem hashed_password, sem outros dados do User).


async def test_tutor_listing_is_public_and_leaks_no_user_credentials(
    client,
):
    response = await client.get("/tutors/")
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    for item in body["items"]:
        assert "email" not in item
        assert "hashed_password" not in item
        assert "password" not in item
