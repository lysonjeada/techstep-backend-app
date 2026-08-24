"""Fluxo HTTP completo de /interviews.

Ownership/IDOR (404 cruzado entre usuários) já é coberto em
tests/security/test_idor.py e não é duplicado aqui. Este arquivo cobre
criação, validação, persistência, listagem/ordenação, atualização
parcial, exclusão e rollback em falha de banco.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import SQLAlchemyError

from tests import factories

pytestmark = pytest.mark.integration


VALID_PAYLOAD = {
    "company_name": "Empresa X",
    "job_title": "Engenheiro de Software",
    "job_seniority": "Pleno",
}


# --- POST /interviews/ ---


async def test_create_interview_without_auth_returns_401(client):
    response = await client.post("/interviews/", json=VALID_PAYLOAD)
    assert response.status_code == 401


async def test_create_interview_persists_and_returns_it(
    authenticated_client, user, db_session
):
    response = await authenticated_client.post(
        "/interviews/", json=VALID_PAYLOAD
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["company_name"] == "Empresa X"

    from app import models

    stored = (
        db_session.query(models.Interview)
        .filter(models.Interview.id == body["id"])
        .first()
    )
    assert stored is not None
    assert stored.user_id == user.id


async def test_create_interview_user_id_comes_from_token_not_payload(
    authenticated_client, user, second_user
):
    payload = dict(VALID_PAYLOAD, user_id=str(second_user.id))

    response = await authenticated_client.post(
        "/interviews/", json=payload
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(user.id)


async def test_create_interview_missing_required_field_returns_422(
    authenticated_client,
):
    response = await authenticated_client.post(
        "/interviews/", json={"job_title": "Engenheiro"}
    )
    assert response.status_code == 422


# --- GET /interviews/ ---


async def test_list_interviews_returns_empty_list_when_none_exist(
    authenticated_client,
):
    response = await authenticated_client.get("/interviews/")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_interviews_orders_by_created_at_desc(
    authenticated_client, db_session, user
):
    # `func.now()` do Postgres retorna o mesmo valor para todos os
    # statements dentro da mesma transação (o savepoint do db_session
    # de teste conta como uma única transação real), então fixamos
    # created_at explicitamente para garantir uma ordem determinística.
    base_time = datetime.now(timezone.utc)
    first = factories.create_interview(
        db_session,
        user,
        company_name="Primeira",
        created_at=base_time - timedelta(minutes=5),
    )
    second = factories.create_interview(
        db_session,
        user,
        company_name="Segunda",
        created_at=base_time,
    )

    response = await authenticated_client.get("/interviews/")
    assert response.status_code == 200

    ids = [item["id"] for item in response.json()]
    assert ids == [str(second.id), str(first.id)]


# --- GET /interviews/{id} ---


async def test_read_interview_returns_404_for_unknown_id(
    authenticated_client,
):
    response = await authenticated_client.get(
        "/interviews/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


async def test_read_existing_interview_returns_it(
    authenticated_client, db_session, user
):
    interview = factories.create_interview(db_session, user)

    response = await authenticated_client.get(
        f"/interviews/{interview.id}"
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(interview.id)


# --- PUT /interviews/{id} ---


async def test_update_interview_applies_full_payload(
    authenticated_client, db_session, user
):
    interview = factories.create_interview(db_session, user)

    payload = dict(VALID_PAYLOAD, company_name="Empresa Atualizada")
    response = await authenticated_client.put(
        f"/interviews/{interview.id}", json=payload
    )

    assert response.status_code == 200
    assert response.json()["company_name"] == "Empresa Atualizada"


async def test_update_interview_unknown_id_returns_404(
    authenticated_client,
):
    response = await authenticated_client.put(
        "/interviews/00000000-0000-0000-0000-000000000000",
        json=VALID_PAYLOAD,
    )
    assert response.status_code == 404


async def test_update_interview_rolls_back_on_db_commit_failure(
    authenticated_client, db_session, user, monkeypatch
):
    interview = factories.create_interview(
        db_session, user, company_name="Original"
    )

    def _boom(*args, **kwargs):
        raise SQLAlchemyError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", _boom)

    response = await authenticated_client.put(
        f"/interviews/{interview.id}",
        json=dict(VALID_PAYLOAD, company_name="Nao Deve Salvar"),
    )

    assert response.status_code == 500

    monkeypatch.undo()
    db_session.rollback()
    db_session.expire_all()

    from app import models

    stored = (
        db_session.query(models.Interview)
        .filter(models.Interview.id == interview.id)
        .first()
    )
    assert stored.company_name == "Original"


# --- DELETE /interviews/{id} ---


async def test_delete_interview_removes_it(
    authenticated_client, db_session, user
):
    interview = factories.create_interview(db_session, user)

    response = await authenticated_client.delete(
        f"/interviews/{interview.id}"
    )
    assert response.status_code == 200

    db_session.expire_all()
    from app import models

    stored = (
        db_session.query(models.Interview)
        .filter(models.Interview.id == interview.id)
        .first()
    )
    assert stored is None


async def test_delete_interview_unknown_id_returns_404(
    authenticated_client,
):
    response = await authenticated_client.delete(
        "/interviews/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


# --- GET /interviews/next/ ---


async def test_next_interviews_includes_today_and_future_only(
    authenticated_client, db_session, user
):
    today = date.today()

    today_interview = factories.create_interview(
        db_session, user, next_interview_date=today
    )
    future_interview = factories.create_interview(
        db_session, user, next_interview_date=today + timedelta(days=5)
    )
    factories.create_interview(
        db_session, user, next_interview_date=today - timedelta(days=1)
    )
    factories.create_interview(db_session, user, next_interview_date=None)

    response = await authenticated_client.get("/interviews/next/")
    assert response.status_code == 200

    ids = [item["id"] for item in response.json()]
    assert ids == [str(today_interview.id), str(future_interview.id)]


async def test_next_interviews_only_includes_own_interviews(
    authenticated_client, db_session, user, second_user
):
    today = date.today()

    factories.create_interview(
        db_session, second_user, next_interview_date=today
    )

    response = await authenticated_client.get("/interviews/next/")
    assert response.status_code == 200
    assert response.json() == []


async def test_next_interviews_without_auth_returns_401(client):
    response = await client.get("/interviews/next/")
    assert response.status_code == 401
